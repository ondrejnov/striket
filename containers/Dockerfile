# Striket sandbox: tooling for authorized white-box (and later black-box) testing.
# Adapted from Strix's image; the Caido proxy and Strix-engine specifics are dropped.
# Build from the repo root:  docker build -f containers/Dockerfile -t striket-sandbox .

# Builder stage: compile Go tools so the toolchain never reaches the runtime image.
FROM kalilinux/kali-rolling:latest AS gobuilder

RUN apt-get update && \
    apt-get install -y kali-archive-keyring && \
    apt-get update && \
    apt-get install -y --no-install-recommends golang-go git ca-certificates

ENV GOBIN=/out/bin
RUN mkdir -p /out/bin && \
    go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest && \
    go install -v github.com/projectdiscovery/katana/cmd/katana@latest && \
    go install -v golang.org/x/vuln/cmd/govulncheck@latest

# Runtime stage
FROM kalilinux/kali-rolling:latest

LABEL description="Striket sandbox for authorized security testing"

RUN apt-get update && \
    apt-get install -y kali-archive-keyring sudo && \
    apt-get update && \
    apt-get upgrade -y

RUN useradd -m -s /bin/bash pentester && \
    usermod -aG sudo pentester && \
    echo "pentester ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers && \
    touch /home/pentester/.hushlogin

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    wget curl git vim nano unzip tar \
    apt-transport-https ca-certificates gnupg lsb-release \
    gcc libc6-dev \
    python3 python3-pip python3-venv python3-setuptools \
    net-tools dnsutils \
    file xxd \
    jq parallel ripgrep grep \
    less procps \
    iproute2 iputils-ping netcat-traditional \
    nmap nuclei ffuf \
    nodejs npm pipx \
    libcap2-bin \
    chromium fonts-liberation

RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

USER pentester
WORKDIR /tmp

COPY --from=gobuilder --chown=pentester:pentester /out/bin/ /home/pentester/go/bin/

RUN pipx install semgrep && \
    pipx install bandit

ENV NPM_CONFIG_PREFIX=/home/pentester/.npm-global
RUN mkdir -p /home/pentester/.npm-global && \
    npm install -g retire@latest && \
    npm install -g eslint@latest && \
    npm install -g @ast-grep/cli@latest && \
    npm install -g tree-sitter-cli@latest && \
    npm install -g agent-browser@0.26.0 && \
    npm cache clean --force

ENV AGENT_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium
ENV AGENT_BROWSER_ARGS="--no-first-run,--no-default-browser-check,--lang=en-US"
ENV AGENT_BROWSER_SCREENSHOT_DIR=/workspace/.agent-browser-screenshots
ENV AGENT_BROWSER_IDLE_TIMEOUT_MS=180000
RUN /home/pentester/.npm-global/bin/agent-browser doctor --offline --quick

USER root

# Secret scanning and SCA scanners (gitleaks pinned via ARG; trivy via official installer).
ARG GITLEAKS_VERSION=8.28.0
RUN set -eux; \
    case "$(uname -m)" in \
        x86_64) GL_ARCH="x64" ;; \
        aarch64|arm64) GL_ARCH="arm64" ;; \
        *) echo "Unsupported architecture" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${GL_ARCH}.tar.gz" -o /tmp/gitleaks.tgz; \
    tar -xzf /tmp/gitleaks.tgz -C /tmp gitleaks; \
    install -m 0755 /tmp/gitleaks /usr/local/bin/gitleaks; \
    rm -f /tmp/gitleaks /tmp/gitleaks.tgz
RUN curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin

RUN apt-get autoremove -y && apt-get autoclean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /usr/share/doc/* /usr/share/man/*

ENV PATH="/home/pentester/go/bin:/home/pentester/.local/bin:/home/pentester/.npm-global/bin:$PATH"

# Login shells reset PATH on Debian/Kali; persist it for `bash -lc`.
RUN echo 'export PATH="/home/pentester/go/bin:/home/pentester/.local/bin:/home/pentester/.npm-global/bin:$PATH"' >> /home/pentester/.bashrc && \
    echo 'export PATH="/home/pentester/go/bin:/home/pentester/.local/bin:/home/pentester/.npm-global/bin:$PATH"' >> /home/pentester/.profile

RUN mkdir -p /workspace && chown pentester:pentester /workspace

COPY containers/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# No secrets are baked into the image; LLM/API keys are injected at runtime by the orchestrator.
USER pentester
WORKDIR /workspace
ENTRYPOINT ["docker-entrypoint.sh"]
