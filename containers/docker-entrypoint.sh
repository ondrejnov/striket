#!/bin/bash
set -e

# Remap the in-container user to the host UID/GID so files written to the
# bind-mounted /workspace are owned by the invoking user.
if [ -n "${STRIKET_HOST_UID:-}" ] && [ "${STRIKET_HOST_UID}" != "0" ] && [ "${STRIKET_HOST_UID}" != "$(id -u)" ]; then
  exec sudo -E -- bash -c '
    set -e
    gid="${STRIKET_HOST_GID:-$STRIKET_HOST_UID}"
    old_uid="$1"
    old_gid="$2"
    export PATH="$3"
    shift 3
    sed -i "s|^pentester:x:${old_uid}:${old_gid}:|pentester:x:${STRIKET_HOST_UID}:${gid}:|" /etc/passwd
    sed -i "s|^pentester:x:${old_gid}:|pentester:x:${gid}:|" /etc/group
    chown -R "${STRIKET_HOST_UID}:${gid}" /home/pentester
    chown "${STRIKET_HOST_UID}:${gid}" /workspace
    exec setpriv --reuid "${STRIKET_HOST_UID}" --regid "${gid}" --init-groups "$0" "$@"
  ' "$0" "$(id -u)" "$(id -g)" "$PATH" "$@"
fi

mkdir -p /workspace/.agent-browser-screenshots

cd /workspace
exec "$@"
