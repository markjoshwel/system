# system

my {root,dot,home}files

```text
.
├── README.md
├── etc
│   ├── conf.d
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
│           ├── 00cpuflags
│           └── installkernel
├── heart
│   ├── kernel-6.12.41-default.config
│   ├── kernel-6.12.41-localmodconfig..config
│   ├── kernel-6.12.41-localyesconfig.config
│   └── references
├── install-commands.txt
└── set.py
```

an example of using it whilst installing gentoo:

```text
sudo SYSTEMSET_PREFIX="/mnt/gentoo" SYSTEMSET_USER="majo" python3 set.py
```
