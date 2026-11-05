# The agent's sandbox and the hidden-check runner (one image, fresh container each time).
FROM python@sha256:db20d8506e2f15b6db39b40b6015ca46bae855dec6dd326d462cfe79ae972893
RUN pip install --no-cache-dir pytest==8.3.3 \
 && useradd -u 1000 -m agent \
 && mkdir /workspace && chown 1000:1000 /workspace
USER 1000:1000
WORKDIR /workspace
