# Northstar System Desk

Northstar is a native Fedora desktop utility built with GTK 4, libadwaita, and
Python. It combines a live hardware dashboard, a local file browser, application
launching, and a user-process inspector in one compact window.

## Features

- Separate live CPU, GPU, memory, storage, network throughput, battery, power,
  and temperature metrics, plus uptime and process counts. Unsupported sensors
  are shown as unavailable.
- Browse folders, open files with their desktop default application, create
  folders, and move items to Trash with a confirmation step.
- Launch installed desktop applications and inspect supported application files
  in `~/Downloads`. Executable AppImages can be launched directly.
- Inspect processes owned by the current user and send a normal termination
  signal only after an explicit confirmation.
- Change the system power profile when `power-profiles-daemon` is available; the
  selector is disabled when the service or hardware support is unavailable.
- No daemon, root access, or background service is required.

## Run from source

On Fedora, install the runtime dependencies and launch the application:

```sh
sudo dnf install python3 python3-gobject python3-psutil gtk4 libadwaita
PYTHONPATH=src python3 -m northstar.app
```

## Build an RPM

Install the packaging tools and runtime dependencies:

```sh
sudo dnf install rpm-build desktop-file-utils python3 python3-gobject \
  python3-psutil gtk4 libadwaita
```

Build and run the RPM checks:

```sh
bash packaging/build-rpm.sh
```

The binary RPM is written to `~/rpmbuild/RPMS/noarch/`. Install it with:

```sh
sudo dnf install ~/rpmbuild/RPMS/noarch/northstar-0.2.0-1*.noarch.rpm
```

Set `RPMBUILD_DIR` to use a different RPM build tree. The spec installs the
launcher, Python source, desktop entry, and scalable application icon; it runs
the unit tests and validates the desktop file during `%check`.

## Notes

Power draw and temperature depend on kernel and hardware sensor support. A
missing sensor is reported as `N/A`, rather than inferred. Application installer
files are opened with the desktop environment's configured handler; Northstar
does not silently install packages or change system services.