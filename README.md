# system

my {root,dot,home}files

```text
.
├── @darwin
│   ├── etc
│   │   └── nix-darwin
│   │       ├── flake.lock
│   │       └── flake.nix
│   └── home
│       ├── Library
│       │   └── LaunchAgents
│       │       └── co.joshwel.lottedisplayfriend.plist
│       └── Space
│           └── Scripts
│               ├── clean
│               ├── clean-brew
│               ├── clean-nix
│               ├── clean-user-cache
│               └── fix-pkg-quarantine
├── README.md
├── chroot.sh
├── compile-kernel-chroot.sh
├── compile-kernel.sh
├── efi
│   └── EFI
│       └── refind
│           └── refind.conf
├── etc
│   ├── conf.d
│   │   ├── dmcrypt
│   │   └── hostname
│   ├── dhcp
│   │   └── dhclient.conf
│   ├── doas.conf
│   ├── fstab
│   ├── hostname
│   ├── portage
│   │   ├── binrepos.conf
│   │   │   └── gentoobinhost.conf
│   │   ├── env.d
│   │   │   ├── 00local
│   │   │   └── 02locale
│   │   ├── make.conf
│   │   └── package.use
│   │       ├── 00cpuflags
│   │       ├── doas
│   │       ├── kernel
│   │       └── networking
│   └── ugrd
│       └── config.toml
├── heart
│   ├── kernel-6.12.41-default.config
│   ├── kernel-6.12.41-localmodconfig.config
│   ├── kernel-6.12.41-localyesconfig.config
│   └── kernel-6.12.41-majorette.config
├── home
│   └── Space
│       └── Scripts
│           ├── convert-meadowpatch
│           └── nixstall
├── install-commands.txt
└── tooling.py
```

an example of using it whilst installing gentoo:

```text
sudo MST_PREFIX="/mnt/gentoo/" MST_USER="majo" python3 tooling.py files set
```
