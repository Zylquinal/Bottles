# installer_manager.py
#
# Copyright 2020 brombinmirko <send@mirko.pm>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import yaml
import urllib.request
from typing import Union, NewType
from datetime import datetime
from gi.repository import Gtk, GLib

from .runner import Runner
from .globals import BottlesRepositories, Paths
from ..utils import RunAsync, UtilsLogger
from .component import ComponentManager

logging = UtilsLogger()

# Define custom types for better understanding of the code
BottleConfig = NewType('BottleConfig', dict)
RunnerName = NewType('RunnerName', str)
RunnerType = NewType('RunnerType', str)

class InstallerManager:

    def __init__(
        self, 
        manager,
        widget:Gtk.Widget=None
    ):
        self.__manager = manager
        self.__utils_conn = manager.utils_conn
        self.__component_manager = manager.component_manager

    def get_installer(
        self, 
        installer_name: str, 
        installer_category: str, 
        plain: bool = False
    ) -> Union[str, dict, bool]:
        '''
        This function can be used to fetch the manifest for a given
        installer. It can be returned as plain text or as a dictionary.
        It will return False if the installer is not found.
        '''
        if self.__utils_conn.check_connection():
            try:
                with urllib.request.urlopen("%s/%s/%s.yml" % (
                    BottlesRepositories.installers,
                    installer_category,
                    installer_name
                )) as url:
                    if plain:
                        '''
                        Caller required the component manifest
                        as plain text.
                        '''
                        return url.read().decode("utf-8")

                    # return as dictionary
                    return yaml.safe_load(url.read())
            except:
                logging.error(f"Cannot fetch manifest for {installer_name}.")
                return False

        return False

    def __download_icon(self, configuration, executable:dict, manifest):
        icon_url = "%s/data/%s/%s" % (
            BottlesRepositories.installers,
            manifest.get('Name'),
            executable.get('icon')
        )
        bottle_icons_path = f"{Runner().get_bottle_path(configuration)}/icons"
        icon_path = f"{bottle_icons_path}/{executable.get('icon')}"

        if not os.path.exists(bottle_icons_path):
            os.makedirs(bottle_icons_path)
        if not os.path.isfile(icon_path):
            urllib.request.urlretrieve(icon_url, icon_path)

    def __install_dependencies(self, configuration, dependencies:list):
        for dep in dependencies:
            if dep in configuration.get("Installed_Dependencies"):
                continue
            dep_index = [dep, self.__manager.supported_dependencies.get(dep)]
            self.__manager.async_install_dependency([
                configuration, 
                dep_index, 
                None
            ])

    def __perform_steps(self, configuration, steps:list):
        for st in steps:
            # Step type: install_exe, install_msi
            if st["action"] in ["install_exe", "install_msi"]:
                download = self.__component_manager.download(
                    "installer",
                    st.get("url"),
                    st.get("file_name"),
                    st.get("rename"),
                    checksum=st.get("file_checksum"))

                if download:
                    if st.get("rename"):
                        file = st.get("rename")
                    else:
                        file = st.get("file_name")

                    Runner().run_executable(
                        configuration=configuration,
                        file_path=f"{Paths.temp}/{file}",
                        arguments=st.get("arguments"),
                        environment=st.get("environment"))
    
    def __set_parameters(self, configuration, parameters:dict):
        if parameters.get("dxvk") and not configuration.get("Parameters")["dxvk"]:
            self.__manager.install_dxvk(configuration)

        if parameters.get("vkd3d") and configuration.get("Parameters")["vkd3d"]:
            self.__manager.install_vkd3d(configuration)

        for param in parameters:
            self.__manager.update_configuration(
                configuration=configuration,
                key=param,
                value=parameters[param],
                scope="Parameters"
            )

    def __set_executable_arguments(self, configuration, executable:dict):
        self.__manager.update_configuration(
            configuration=configuration,
            key=executable.get("file"),
            value=executable.get("arguments"),
            scope="Programs")

    def __create_desktop_entry(self, configuration, manifest, executable:dict):
        bottle_icons_path = f"{Runner().get_bottle_path(configuration)}/icons"

        icon_path = f"{bottle_icons_path}/{executable.get('icon')}"
        desktop_file = "%s/%s--%s--%s.desktop" % (
            Paths.applications,
            configuration.get('Name'),
            manifest.get('Name'),
            datetime.now().timestamp()
        )

        if "FLATPAK_ID" in os.environ:
            return None
            
        with open(desktop_file, "w") as f:
            ex_path = "%s/%s/drive_c/%s/%s" % (
                Paths.bottles,
                configuration.get('Path'),
                executable.get('path'),
                executable.get('file')
            )
            f.write(f"[Desktop Entry]\n")
            f.write(f"Name={executable.get('name')}\n")
            f.write(f"Exec=bottles -e '{ex_path}' -b '{configuration.get('Name')}'\n")
            f.write(f"Type=Application\n")
            f.write(f"Terminal=false\n")
            f.write(f"Categories=Application;\n")
            if executable.get("icon"):
                f.write(f"Icon={icon_path}\n")
            else:
                f.write(f"Icon=com.usebottles.bottles")
            f.write(f"Comment={manifest.get('Description')}\n")
            # Actions
            f.write("Actions=Configure;\n")
            f.write("[Desktop Action Configure]\n")
            f.write("Name=Configure in Bottles\n")
            f.write(f"Exec=bottles -b '{configuration.get('Name')}'\n")
    
    def __async_install(self, args) -> None:
        configuration, installer, widget = args

        manifest = self.get_installer(
            installer_name = installer[0],
            installer_category = installer[1]["Category"]
        )
        dependencies = manifest.get("Dependencies")
        parameters = manifest.get("Parameters")
        executable = manifest.get("Executable")
        steps = manifest.get("Steps")

        # download icon
        if executable.get("icon"):
            self.__download_icon(configuration, executable, manifest)
        
        # install dependencies
        if dependencies:
            self.__install_dependencies(configuration, dependencies)
        
        # execute steps
        if steps:
            self.__perform_steps(configuration, steps)
        
        # set parameters
        if parameters:
            self.__set_parameters(configuration, parameters)

        # register executable arguments
        if executable.get("arguments"):
            self.__set_executable_arguments(configuration, executable)

        # create Desktop entry
        self.__create_desktop_entry(configuration, manifest, executable)

        # unlock widget
        if widget is not None:
            GLib.idle_add(widget.set_installed)
    
    def install(self, configuration, installer, widget) -> None:
        RunAsync(self.__async_install, False, [configuration, installer, widget])