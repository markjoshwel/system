#!/bin/sh

set -euo pipefail

if [ "`id -u`" -ne 0 ]; then
 echo "note: switching from `id -un` to root"
 exec sudo "$0"
 exit 99
fi

# livecd /mnt/gentoo # lsblk -f
# nvme0n1
# ├─nvme0n1p1 vfat        FAT32            ESP                  7301-94FE                             941.8M     8% /mnt/gentoo/efi
# ├─nvme0n1p2                              MSR
# ├─nvme0n1p3                              Windows
# ├─nvme0n1p4 ntfs                         WinRE                20A8408F5052D321
# ├─nvme0n1p5 swap        1                Swap                 05fd15ba-79db-4e2f-8265-1afd09c012a9                [SWAP]
# ├─nvme0n1p6 crypto_LUKS 2                                     07abad04-6ca3-447e-a3b9-39b132355e8d
# │ └─root    btrfs                        Linux                4a5e76e7-bbe8-49d5-b854-37673ce2b17e  602.1G     0% /mnt/gentoo
# └─nvme0n1p7                              Shared

cryptsetup luksOpen /dev/nvme0n1p6 gentoo

mount /dev/mapper/gentoo /mnt/gentoo
mkdir -p /mnt/gentoo/efi
mount /dev/nvme0n1p1 /mnt/gentoo/efi
swapon /dev/nvme0n1p5

cp --dereference /etc/resolv.conf /mnt/gentoo/etc/

if command -v arch-chroot >/dev/null 2>&1; then
    echo 'run the following manually:'
    echo ' ... export PS1="(chroot) ${PS1}"'
    arch-chroot /mnt/gentoo
else
    mount --types proc /proc /mnt/gentoo/proc
    mount --rbind /sys /mnt/gentoo/sys
    mount --make-rslave /mnt/gentoo/sys
    mount --rbind /dev /mnt/gentoo/dev
    mount --make-rslave /mnt/gentoo/dev
    mount --bind /run /mnt/gentoo/run
    mount --make-slave /mnt/gentoo/run

    test -L /dev/shm && rm /dev/shm && mkdir /dev/shm
    mount --types tmpfs --options nosuid,nodev,noexec shm /dev/shm
    chmod 1777 /dev/shm /run/shm

    echo 'run the following manually:'
    echo ' ... source /etc/profile'
    echo ' ... export PS1="(chroot) ${PS1}"'
    chroot /mnt/gentoo /bin/bash
fi

arch-chroot /mnt/gentoo
