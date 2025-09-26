# system

my {root,dot,home}files

```text
.
├── README.md
├── etc
│   └── portage
│       ├── binrepos.conf
│       │   └── gentoobinhost.conf
│       ├── env.d
│       │   ├── 00local
│       │   └── 02locale
│       ├── make.conf
│       └── package.use
│           └── 00cpuflags
├── install-commands.txt
└── set.py
```

an example of using it whilst installing gentoo:

```text
sudo SYSTEMSET_PREFIX="/mnt/gentoo" SYSTEMSET_USER="majo" python3 set.py
```
