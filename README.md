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
├── @linux
│   └── .gitkeep
├── @windows
│   └── .gitkeep
├── chroot.sh
├── etc
│   ├── conf.d
│   │   ├── .systemsyncdir
│   │   └── dmcrypt
│   ├── dracut.conf.d
│   │   └── luks.conf
│   ├── fstab
│   ├── hostname
│   └── portage
│       ├── binrepos.conf
│       │   └── gentoobinhost.conf
│       ├── env.d
│       │   ├── 00local
│       │   └── 02locale
│       ├── make.conf
│       └── package.use
│           └── 00cpuflags
├── heart
│   ├── kernel-6.12.41-default.config
│   ├── kernel-6.12.41-localmodconfig.config
│   ├── kernel-6.12.41-localyesconfig.config
│   ├── kernel-6.12.41-majorette.config
│   ├── kernel-6.12.41-majorette+localmodconfig.config
│   └── references
├── home
│   └── Space
│       └── Scripts
│           ├── convert-meadowpatch
│           └── nixstall
├── install-commands.txt
├── README.md
└── tooling.py
```

an example of using it whilst installing gentoo:

```text
sudo SYSTEMSET_PREFIX="/mnt/gentoo" SYSTEMSET_USER="majo" python3 tooling.py files set
```
