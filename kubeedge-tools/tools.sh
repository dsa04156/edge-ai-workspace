#!/usr/bin/env bash

set -o errexit
set -o nounset
set -o pipefail

arch="$(uname -m)"
toolarch=""
tarball_dir=./tarball
config_dir=./config
yamls_dir=./yamls
patch_dir=./patch
crictl_version=v1.20.0
cni_version=v0.9.0
flannel_version=v0.28.3
flannel_cni_plugin_version=v1.9.1-flannel1

function pull_and_save_image() {
    local image=$1
    local arch=$2
    local out_tar=$3

    if command -v docker >/dev/null 2>&1; then
        docker pull --platform=linux/$arch "$image"
        docker save -o "$out_tar" "$image"
    elif command -v nerdctl >/dev/null 2>&1; then
        nerdctl -n k8s.io pull --platform=linux/$arch "$image"
        nerdctl -n k8s.io save -o "$out_tar" "$image"
    elif command -v ctr >/dev/null 2>&1; then
        ctr -n k8s.io images pull --platform linux/$arch "$image"
        ctr -n k8s.io images export "$out_tar" "$image"
    else
        echo "no supported runtime found for image download (docker/nerdctl/ctr)"
        return 1
    fi
}

function arch_to_toolarch() {
    case $1 in
    x86_64)
        toolarch="amd64"
        ;;
    aarch64)
        toolarch="arm64"
        ;;
    *)
        echo "unsupported arch: $arch [x86_64|aarch64]"
        exit 1
        ;;
    esac
    echo "get toolarch: $toolarch"
}

function download_crictl_tarball() {
    local arch=$1
    echo "download crictl tarball: $arch"
    wget -P $tarball_dir --no-check-certificate https://github.com/kubernetes-sigs/cri-tools/releases/download/$crictl_version/crictl-$crictl_version-linux-$arch.tar.gz
}

function clean_crictl_tarball() {
    local arch=$1
    echo "clean crictl tarball: $arch"
    rm -rf $tarball_dir/crictl-$crictl_version-linux-$arch.tar.gz
}

function install_crictl() {
    echo "install crictl"
    if command -v crictl >/dev/null 2>&1; then
        echo "keep existing crictl: $(crictl --version 2>/dev/null || true)"
        return 0
    fi
    tar zxvf $tarball_dir/crictl-$crictl_version-linux-$toolarch.tar.gz -C /usr/local/bin
}

function download_cni_tarball() {
    local arch=$1
    echo "download cni tarball: $arch"
    wget -P $tarball_dir --no-check-certificate https://github.com/containernetworking/plugins/releases/download/$cni_version/cni-plugins-linux-$arch-$cni_version.tgz
}

function clean_cni_tarball() {
    local arch=$1
    echo "clean cni tarball: $arch"
    rm -rf $tarball_dir/cni-plugins-linux-$arch-$cni_version.tgz
}

function install_cni() {
    echo "install cni"
    local required_plugins=(bridge host-local loopback portmap)
    local plugin
    local complete=1
    for plugin in "${required_plugins[@]}"; do
        if [[ ! -x "/opt/cni/bin/${plugin}" ]]; then
            complete=0
            break
        fi
    done
    if [[ "$complete" == "1" ]]; then
        echo "keep existing CNI plugins in /opt/cni/bin"
        return 0
    fi
    mkdir -p /opt/cni/bin
    tar -zxvf $tarball_dir/cni-plugins-linux-$toolarch-$cni_version.tgz -C /opt/cni/bin
}

function download_flannel_image() {
    local arch=$1
    echo "download flannel image: $arch"
    pull_and_save_image "ghcr.io/flannel-io/flannel:$flannel_version" "$arch" "$tarball_dir/flannel-$arch.tar"
    pull_and_save_image "ghcr.io/flannel-io/flannel-cni-plugin:$flannel_cni_plugin_version" "$arch" "$tarball_dir/flannel-cni-plugin-$arch.tar"
}

function load_flannel_image() {
    echo "load flannel image"
    local image_tars=(
        "$tarball_dir/flannel-$toolarch.tar"
        "$tarball_dir/flannel-cni-plugin-$toolarch.tar"
    )

    for image_tar in "${image_tars[@]}"; do
        if [[ ! -f "$image_tar" ]]; then
            echo "skip load: $image_tar not found"
            continue
        fi

        if command -v docker >/dev/null 2>&1; then
            docker load -i "$image_tar"
        elif command -v ctr >/dev/null 2>&1; then
            ctr -n k8s.io images import "$image_tar"
        elif command -v nerdctl >/dev/null 2>&1; then
            nerdctl -n k8s.io load -i "$image_tar"
        else
            echo "no supported runtime found for image load (docker/ctr/nerdctl)"
            return 1
        fi
    done
}

function clean_flannel_image_tarball() {
    local arch=$1
    echo "clean flannel image tarball: $arch"
    rm -rf $tarball_dir/flannel-$arch.tar
    rm -rf $tarball_dir/flannel-cni-plugin-$arch.tar
}

function install_flannel() {
    local mode=$1
    shift
    local action="${1:---check}"
    [[ "$mode" == cloud || "$mode" == edge ]] || return 2
    [[ $# -le 1 && ( "$action" == --check || "$action" == --apply ) ]] || {
        echo 'usage: install-flannel-{cloud,edge}.sh [--check|--apply]' >&2
        return 2
    }
    local root
    root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    local context="${KUBE_CONTEXT:-kubernetes-admin@kubernetes}"
    if [[ -z "${KUBECONFIG:-}" && -r /etc/kubernetes/admin.conf ]]; then
        export KUBECONFIG=/etc/kubernetes/admin.conf
    fi
    local manifests=( -f "$root/yamls/kube-flannel-common.yml"
        -f "$root/config/flannel-interfaces.yaml" -f "$root/yamls/kube-flannel-$mode.yml" )
    echo "Flannel $mode; context=$context; action=$action"
    kubectl --context "$context" apply --dry-run=server "${manifests[@]}"
    if [[ "$action" == --apply ]]; then
        kubectl --context "$context" apply "${manifests[@]}"
        echo 'OnDelete: existing Pods are not restarted. Verify each node before replacing its exact Flannel Pod.'
    fi
}

function download_kubeedge_pause_image() {
    local arch=$1
    echo "download kubeedge pause image: $arch"
    pull_and_save_image "kubeedge/pause:3.1" "$arch" "$tarball_dir/kubeedge-pause-$arch.tar"
}

function load_kubeedge_pause_image() {
    echo "load kubeedge pause image"
    local image_tar="$tarball_dir/kubeedge-pause-$toolarch.tar"
    if [[ ! -f "$image_tar" ]]; then
        echo "skip load: $image_tar not found"
        return 0
    fi

    if command -v docker >/dev/null 2>&1; then
        docker load -i "$image_tar"
    elif command -v ctr >/dev/null 2>&1; then
        ctr -n k8s.io images import "$image_tar"
    elif command -v nerdctl >/dev/null 2>&1; then
        nerdctl -n k8s.io load -i "$image_tar"
    else
        echo "no supported runtime found for image load (docker/ctr/nerdctl)"
        return 1
    fi
}

function clean_kubeedge_pause_image_tarball() {
    local arch=$1
    echo "clean kubeedge pause image tarball: $arch"
    rm -rf $tarball_dir/kubeedge-pause-$arch.tar
}

function download_nginx_image() {
    local arch=$1
    echo "download nginx image: $arch"
    pull_and_save_image "nginx:alpine" "$arch" "$tarball_dir/nginx-$arch.tar"
}

function load_nginx_image() {
    echo "load nginx image"
    local image_tar="$tarball_dir/nginx-$toolarch.tar"
    if [[ ! -f "$image_tar" ]]; then
        echo "skip load: $image_tar not found"
        return 0
    fi

    if command -v docker >/dev/null 2>&1; then
        docker load -i "$image_tar"
    elif command -v ctr >/dev/null 2>&1; then
        ctr -n k8s.io images import "$image_tar"
    elif command -v nerdctl >/dev/null 2>&1; then
        nerdctl -n k8s.io load -i "$image_tar"
    else
        echo "no supported runtime found for image load (docker/ctr/nerdctl)"
        return 1
    fi
}

function clean_nginx_image_tarball() {
    local arch=$1
    echo "clean nginx image tarball: $arch"
    rm -rf $tarball_dir/nginx-$arch.tar
}

function patch_kubeedge_component() {
    local ke_component=$1
    patch /etc/kubeedge/config/$ke_component.yaml < $patch_dir/$ke_component.yaml.patch
}
