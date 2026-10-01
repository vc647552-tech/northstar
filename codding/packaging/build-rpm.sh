#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
name="northstar"
version="$(awk '$1 == "Version:" { print $2; exit }' "$root/packaging/northstar.spec")"
topdir="${RPMBUILD_DIR:-$HOME/rpmbuild}"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

mkdir -p "$topdir"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
mkdir "$staging/$name-$version"
tar --exclude-vcs --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='dist' --exclude='build' --exclude='.venv' \
    -C "$root" -cf - . | tar -C "$staging/$name-$version" -xf -
tar -C "$staging" -czf "$topdir/SOURCES/$name-$version.tar.gz" "$name-$version"

rpmbuild -ba --define "_topdir $topdir" "$root/packaging/northstar.spec"
printf '\nRPM packages written to %s/RPMS/noarch/\n' "$topdir"