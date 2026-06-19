# SOC Seattle - Probe Agent
# Ubuntu 24.04 LTS (Noble) + Suricata 7 + Python 3.12 agent
#
# NET_ADMIN and NET_RAW capabilities are required for AF_PACKET capture.
# Run with: docker run --cap-add=NET_ADMIN --cap-add=NET_RAW --network=host ...

FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive

# -- System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    gnupg2 \
    curl \
    ca-certificates \
    && add-apt-repository ppa:oisf/suricata-stable \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        suricata \
        python3.12 \
        python3.12-venv \
        python3-pip \
        tcpdump \
        libpcap-dev \
        iproute2 \
        net-tools \
        procps \
        jq \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# -- Suricata directories
RUN mkdir -p \
    /etc/suricata/rules \
    /var/log/suricata \
    /var/run/suricata \
    /opt/pcap

# suricata.yaml.template has %INTERFACE% / %BPF_FILTER% placeholders
# replaced at runtime by the agent before writing suricata.yaml
COPY suricata/suricata.yaml /etc/suricata/suricata.yaml.template
COPY suricata/classification.config /etc/suricata/classification.config
COPY suricata/reference.config      /etc/suricata/reference.config

# -- Python agent
WORKDIR /opt/agent
COPY agent/requirements.txt .

# Use a venv to isolate from Ubuntu system packages (avoids RECORD conflicts)
RUN python3.12 -m venv /opt/venv
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY agent/ .

# -- Non-root user (still needs cap_net_raw for pcap)
RUN groupadd -r pcap || true \
    && groupadd -r probe \
    && useradd -r -g probe -G pcap probe \
    && chown -R probe:probe /opt/agent /var/log/suricata /var/run/suricata /opt/pcap

# -- Entrypoint
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV SURICATA_LOG_DIR=/var/log/suricata
ENV PCAP_DIR=/opt/pcap

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python3.12", "main.py"]
