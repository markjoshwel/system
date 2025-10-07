#!/bin/sh
if [ ! -d "/usr/src/linux" ]; then
  echo "error: dir /usr/src/linux not found"
  exit 1
fi

# compile
(cd /usr/src/linux; make -j16 -l16 && make modules_install)

# careful!
rm /boot/System.map*
rm /boot/config-*
rm /boot/vmlinuz-*
rm /boot/initramfs-*
rm /efi/EFI/Gentoo/amd-uc.img
rm /efi/EFI/Gentoo/initramfs.img
rm /efi/EFI/Gentoo/vmlinuz

# re-emerge firmware
emerge sys-kernel/linux-firmware sys-firmware/sof-firmware

# install kernel
(cd /usr/src/linux; make install)
cp /boot/amd-uc.img /efi/EFI/Gentoo/microcode.img  # microcode
cp /boot/initramfs-*.img /efi/EFI/Gentoo/initramfs.img
cp /boot/vmlinuz-* /efi/EFI/Gentoo/vmlinuz
