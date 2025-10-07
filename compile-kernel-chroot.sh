#!/bin/sh
set -euo pipefail

if [ "`id -u`" -ne 0 ]; then
 echo "note: switching from `id -un` to root"
 exec sudo "$0"
 exit 99
fi

if [ ! -d "/mnt/gentoo" ]; then
  echo "error: dir /mnt/gentoo not found"
  exit 1
fi

sudo arch-chroot /mnt/gentoo /bin/bash < compile-kernel.sh
