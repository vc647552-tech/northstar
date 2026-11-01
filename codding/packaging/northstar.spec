Name:           northstar
Version:        0.2.0
Release:        1%{?dist}
Summary:        Native desktop file manager and system monitor
License:        MIT
BuildArch:      noarch
Source0:        %{name}-%{version}.tar.gz
BuildRequires:  desktop-file-utils
BuildRequires:  python3
BuildRequires:  python3-psutil
Requires:       gtk4
Requires:       libadwaita
Requires:       python3-gobject
Requires:       python3-psutil
Recommends:     power-profiles-daemon

%description
Northstar is a native GTK4 and libadwaita desktop application for browsing
local files, launching applications, inspecting user processes, and monitoring
live system health metrics.

%prep
%autosetup -n %{name}-%{version}

%build

%check
PYTHONPATH=src python3 -m unittest discover -s tests -v
desktop-file-validate packaging/io.github.northstar.SystemDesk.desktop

%install
install -Dpm 0755 bin/northstar %{buildroot}%{_bindir}/northstar
install -dpm 0755 %{buildroot}%{_datadir}/northstar/northstar
install -pm 0644 src/northstar/*.py %{buildroot}%{_datadir}/northstar/northstar/
install -Dpm 0644 packaging/io.github.northstar.SystemDesk.desktop \
    %{buildroot}%{_datadir}/applications/io.github.northstar.SystemDesk.desktop
install -Dpm 0644 packaging/io.github.northstar.SystemDesk.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.northstar.SystemDesk.svg
install -Dpm 0644 LICENSE %{buildroot}%{_licensedir}/%{name}/LICENSE

%files
%license %{_licensedir}/%{name}/LICENSE
%{_bindir}/northstar
%{_datadir}/northstar/northstar/
%{_datadir}/applications/io.github.northstar.SystemDesk.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.northstar.SystemDesk.svg

%changelog
* Sun Nov 01 2026 Northstar contributors - 0.2.0-1
- Add separate CPU, GPU, storage, network, battery, power, and temperature metrics

* Thu Oct 01 2026 Northstar contributors - 0.1.0-1
- Initial release