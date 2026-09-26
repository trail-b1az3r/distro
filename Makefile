# Common tasks. The ISO build itself is ./build.sh (see docs/iso-building.md).
PYTHON ?= python3
export PYTHONPATH := lib

.PHONY: help bootstrap branding test test-unit test-gui test-integration lint check packages plan lock iso iso-container qemu-test installer-demo clean distclean

help:
	@echo "make bootstrap        prepare an Arch/EndeavourOS build host (root)"
	@echo "make branding         generate logos, icons, wallpapers and boot themes from distro.conf"
	@echo "make test             unit, GUI and (as root) loop-device integration tests"
	@echo "make lint             ruff, shellcheck, PKGBUILD and completion checks"
	@echo "make plan             show which packages the distribution repository needs, in build order"
	@echo "make lock             re-pin AUR packages (packages/aur.lock.json)"
	@echo "make packages         build the distribution repository into build/repo"
	@echo "make iso              build the ISO on this Arch-based host"
	@echo "make iso-container    build the ISO in a container (any Linux with Docker/Podman)"
	@echo "make qemu-test        install the newest ISO in QEMU and check the result"
	@echo "make installer-demo   run the graphical installer against a simulated machine"
	@echo "make clean            remove build products (keeps dist/)"

bootstrap:
	sudo scripts/bootstrap.sh --builder --with-qemu

branding:
	$(PYTHON) -m distrokit.build.branding

test: test-unit test-gui
	@if [ "$$(id -u)" = 0 ]; then $(PYTHON) -m pytest tests/integration; else echo "integration tests need root (sudo make test-integration)"; fi

test-unit:
	$(PYTHON) -m pytest tests/unit

test-gui:
	QT_QPA_PLATFORM=offscreen $(PYTHON) -m pytest tests/gui

test-integration:
	$(PYTHON) -m pytest tests/integration

lint check:
	scripts/check.sh

plan:
	scripts/build-packages.sh --plan

lock:
	scripts/build-packages.sh --update-lock

packages:
	scripts/build-packages.sh

iso:
	./build.sh $(ARGS)

iso-container:
	./build.sh --container $(ARGS)

qemu-test:
	tests/qemu/run.sh $(ARGS)

installer-demo:
	$(PYTHON) -m distrokit.installer.main --demo

clean:
	rm -rf build branding/generated .pytest_cache
	find . -name __pycache__ -not -path './desktop/dots/*' -prune -exec rm -rf {} +

distclean: clean
	rm -rf dist checksums metadata
