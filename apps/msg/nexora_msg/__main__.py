import sys


def main() -> int:
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-qt") and sys.argv[1] not in ("--gui",):
        from .cli import main as cli
        return cli(sys.argv[1:])
    from .app import main as gui
    return gui([a for a in sys.argv if a != "--gui"])


if __name__ == "__main__":
    sys.exit(main())
