"""Real model code path with a tiny random Qwen3.5 (no download): capture, replay, steering hook."""
import numpy as np
import pytest

torch = pytest.importorskip("torch")
tokenizers = pytest.importorskip("tokenizers")

from transformers import PreTrainedTokenizerFast, Qwen3_5ForCausalLM, Qwen3_5TextConfig  # noqa: E402

from truthgate.backends import HFBackend, find_layers  # noqa: E402
from truthgate.episode import run_episode  # noqa: E402
from truthgate.steer import add_direction, steer_test  # noqa: E402
from truthgate.tasks import make_task  # noqa: E402

TEMPLATE = ("{% for m in messages %}<|im_start|>{{ m['role'] }}\n{{ m['content'] }}<|im_end|>\n{% endfor %}"
            "{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}")


def tiny():
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers, decoders
    tok = Tokenizer(models.BPE())
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    tr = trainers.BpeTrainer(vocab_size=400, special_tokens=["<|im_start|>", "<|im_end|>", "<tool_call>",
                                                              "</tool_call>"],
                             initial_alphabet=pre_tokenizers.ByteLevel.alphabet())
    tok.train_from_iterator(["def f(x): return x + 1", "run the tests and submit done", '{"name": "submit"}'] * 50,
                            tr)
    t = PreTrainedTokenizerFast(tokenizer_object=tok, eos_token="<|im_end|>", pad_token="<|im_end|>")
    t.chat_template = TEMPLATE
    cfg = Qwen3_5TextConfig(vocab_size=t.vocab_size + 8, hidden_size=64, intermediate_size=128,
                            num_hidden_layers=4, num_attention_heads=4, num_key_value_heads=2, head_dim=16)
    torch.manual_seed(0)
    return Qwen3_5ForCausalLM(cfg), t


@pytest.fixture(scope="module")
def backend():
    m, t = tiny()
    return HFBackend("tiny-qwen3.5", device="cpu", max_new_tokens=12, model=m, tokenizer=t)


def test_capture_shapes(backend):
    out = backend.step([{"role": "user", "content": "hi"}], tools=None)
    for k in ("pre", "gen_mean", "gen_last"):
        assert out["acts"][k].shape == (5, 64)          # embeddings + 4 layers
        assert out["acts"][k].dtype == np.float16
        assert np.isfinite(out["acts"][k]).all()


def test_generation_stops_at_end_of_turn():
    """Qwen3.5 ships no generation_config.json, so generate() alone does not stop at <|im_end|>."""
    m, t = tiny()
    m.generation_config.eos_token_id = None
    b = HFBackend("tiny", device="cpu", max_new_tokens=12, temperature=0, model=m, tokenizer=t)
    bias = torch.zeros(m.config.vocab_size)
    bias[t.convert_tokens_to_ids("<|im_end|>")] = 1e4
    h = m.lm_head.register_forward_hook(lambda _m, _i, out: out + bias)
    try:
        out = b.step([{"role": "user", "content": "hi"}], tools=None)
    finally:
        h.remove()
    assert out["n_gen_tokens"] == 1


def test_episode_with_real_backend(backend):
    t = make_task("clamp", "none", "low")
    ep = run_episode(t, backend, max_steps=2)
    assert ep["label"] == "no_claim"                       # random model never calls submit
    assert len(ep["acts_steps"]) == 2


def test_steering_hook_changes_residual(backend):
    x = backend.tok("run the tests", return_tensors="pt")["input_ids"]
    with torch.no_grad():
        base = backend.model(input_ids=x, output_hidden_states=True).hidden_states
        v = np.zeros(64, dtype=np.float32); v[0] = 100.0
        with add_direction(backend.model, 2, v):
            steered = backend.model(input_ids=x, output_hidden_states=True).hidden_states
        after = backend.model(input_ids=x, output_hidden_states=True).hidden_states
    assert torch.allclose(base[1], steered[1])               # before the hooked layer: unchanged
    assert (steered[2][..., 0] - base[2][..., 0]).abs().min() > 50   # hooked layer output shifted
    assert torch.allclose(base[2], after[2])                 # hook removed afterwards
    assert len(find_layers(backend.model)) == 4


def test_steer_test_runs(backend):
    ep = {"messages": [{"role": "user", "content": "go"}], "submit_msg_index": 1,
          "acts": {"pre": np.ones((1, 5, 64), dtype=np.float16)}}
    res = steer_test(backend, [ep], np.ones(64), layer=2, alphas=(0.0, 2.0), n_samples=2)
    assert res["n_runs"] == 1 and "effect" in res["alphas"]["2.0"]
