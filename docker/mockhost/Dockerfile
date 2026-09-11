# Simulated Oracle Linux 9 target host for development: sshd + rootless Podman.
# It lets developers exercise SSH connection, discovery, package transfer, deployment and lifecycle
# operations without a real server.  NOT for production use.
FROM docker.io/library/oraclelinux:9

RUN dnf -y install openssh-server podman podman-docker fuse-overlayfs slirp4netns shadow-utils \
        tar gzip nmap-ncat curl procps-ng passwd sudo \
    && dnf clean all \
    && ssh-keygen -A \
    && sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config \
    && sed -i 's/^#\?PubkeyAuthentication .*/PubkeyAuthentication yes/' /etc/ssh/sshd_config \
    && sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config \
    && echo "UsePAM yes" >> /etc/ssh/sshd_config

# rootless podman inside a container: use vfs/fuse-overlayfs and disable systemd cgroups
RUN mkdir -p /etc/containers \
    && printf '[storage]\ndriver = "overlay"\n[storage.options.overlay]\nmount_program = "/usr/bin/fuse-overlayfs"\n' > /etc/containers/storage.conf \
    && printf '[engine]\ncgroup_manager = "cgroupfs"\nevents_logger = "file"\n' > /etc/containers/containers.conf

COPY entrypoint.sh /usr/local/bin/mockhost-entrypoint
RUN chmod +x /usr/local/bin/mockhost-entrypoint
EXPOSE 22
ENTRYPOINT ["/usr/local/bin/mockhost-entrypoint"]
