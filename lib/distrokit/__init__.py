"""distrokit: the library behind the distribution's installer, CLI and tools.

The package is deliberately free of third-party dependencies (standard library
only) so that it runs on a minimal system, in the live ISO and inside a
chroot. The graphical front ends in ``distrokit.gui`` are the only modules that
need PySide6.

All user-visible names come from ``distro.conf`` through
:mod:`distrokit.branding`; nothing here hard-codes the distribution's name.
"""

__version__ = "1.0.0"
