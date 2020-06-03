#
# Copyright (c) 2018 Alex Richardson
# All rights reserved.
#
# This software was developed by SRI International and the University of
# Cambridge Computer Laboratory under DARPA/AFRL contract FA8750-10-C-0237
# ("CTSRD"), as part of the DARPA CRASH research programme.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
#
import os
import shlex
import shutil
from subprocess import CalledProcessError
from typing import Any, Dict, Tuple, Union

from .project import (AutotoolsProject, CheriConfig, DefaultInstallDir, GitRepository, MakeCommandKind, Path, Project,
                      SimpleProject)
from ..targets import target_manager
from ..utils import AnsiColour, coloured, commandline_to_str, get_program_version, OSInfo, runCmd, setEnv


class OpamMixin(object):
    config = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert isinstance(self, SimpleProject)
        self.add_required_system_tool("opam", homebrew="opam", cheribuild_target="opam-2.0")  # pytype: disable=attribute-error
        self.required_ocaml_version = "4.06.1"
        self.__using_correct_switch = False
        self.__ignore_switch_version = False

    @property
    def opamroot(self):
        return self.config.cheri_sdk_dir / "opamroot"

    # noinspection PyUnresolvedReferences
    def check_system_dependencies(self):
        super().check_system_dependencies()  # pytype: disable=attribute-error
        opam_path = shutil.which("opam")
        if opam_path:
            opam_version = get_program_version(Path(opam_path), regex=b"(\\d+)\\.(\\d+)\\.?(\\d+)?")
            if opam_version < (2, 0, 0):
                self.dependency_error("Opam version", opam_version, "is too old. Need at least 2.0.0",  # pytype: disable=attribute-error
                                     install_instructions="Install opam 2.0 with your system package manager or run "
                                                          "`cheribuild.py opam-2.0` (Linux-only)")

    @property
    def opam_binary(self):
        return shutil.which("opam") or "opam"

    def _opam_cmd(self, command, *args, _add_switch=True):
        cmdline = [self.opam_binary, command, "--root=" + str(self.opamroot)]
        if _add_switch:
            cmdline.append("--switch=" + self.required_ocaml_version)
        cmdline.extend(args)
        return cmdline

    def _opam_cmd_str(self, command, *args, _add_switch):
        return commandline_to_str(self._opam_cmd(command, *args, _add_switch=_add_switch))

    def _ensure_correct_switch(self):
        if not self.__using_correct_switch and not self.__ignore_switch_version:
            self.__ignore_switch_version = True
            try:
                self.run_opam_cmd("switch", self.required_ocaml_version, _add_switch=False)
            except CalledProcessError:
                # create the switch if it doesn't exist
                self.run_opam_cmd("switch", "--verbose", "--debug", "create", self.required_ocaml_version,
                                  _add_switch=False)
            finally:
                self.__ignore_switch_version = False
            self.__using_correct_switch = True

    def run_opam_cmd(self, command, *args, ignoreErrors=False, _add_switch=True, **kwargs):
        self._ensure_correct_switch()
        command_list = self._opam_cmd(command, *args, _add_switch=_add_switch)
        try:
            return self.run_command_in_ocaml_env(command_list, **kwargs)
        except CalledProcessError:
            if ignoreErrors:
                # noinspection PyUnresolvedReferences
                self.verbose_print(
                    "Ignoring non-zero exit code from " + coloured(AnsiColour.yellow, commandline_to_str(command_list)))
            else:
                raise

    def _run_in_ocaml_env_prepare(self, cwd=None) -> "Tuple[Dict[Any, Union[Union[str, int], Any]], Union[str, Any]]":
        if cwd is None:
            # noinspection PyUnresolvedReferences
            cwd = self.sourceDir if getattr(self, "sourceDir") else "/"  # pytype: disable=attribute-error

        self._ensure_correct_switch()
        opam_env = dict(GIT_TEMPLATE_DIR="",  # see https://github.com/ocaml/opam/issues/3493
                        OPAMROOT=self.opamroot, CCACHE_DISABLE=1,  # https://github.com/ocaml/opam/issues/3395
                        PATH=self.config.dollarPathWithOtherTools)
        if Path(self.opam_binary).is_absolute():
            opam_env["OPAM_USER_PATH_RO"] = Path(self.opam_binary).parent
        if not (self.opamroot / "opam-init").exists():
            # noinspection PyUnresolvedReferences
            self.run_cmd(self.opam_binary, "init", "--root=" + str(self.opamroot), "--no-setup", cwd="/", env=opam_env)  # pytype: disable=attribute-error
        return opam_env, cwd

    def run_in_ocaml_env(self, command: str, cwd=None, print_verbose_only=False, **kwargs):
        opam_env, cwd = self._run_in_ocaml_env_prepare(cwd=cwd)
        script = "eval `opam config env`\n" + command + "\n"
        assert isinstance(self, Project)
        return self.run_shell_script(script, cwd=cwd, print_verbose_only=print_verbose_only, env=opam_env, **kwargs)  # pytype: disable=attribute-error

    def run_command_in_ocaml_env(self, command: list, cwd=None, print_verbose_only=False, **kwargs):
        self._ensure_correct_switch()
        opam_env, cwd = self._run_in_ocaml_env_prepare(cwd=cwd)
        # for opam commands we don't need to prepend opam exec --
        if command[0] != self.opam_binary:
            command = [self.opam_binary, "exec", "--root=" + str(self.opamroot), "--"] + command
        assert isinstance(self, SimpleProject)
        return self.run_cmd(command, cwd=cwd, print_verbose_only=print_verbose_only, env=opam_env, **kwargs)  # pytype: disable=attribute-error


class Opam2(SimpleProject):
    target = "opam-2.0"

    def __init__(self, config):
        super().__init__(config)
        if OSInfo.IS_LINUX:
            self.add_required_system_tool("wget")
            self.add_required_system_tool("bwrap", cheribuild_target="bubblewrap")

    def process(self):
        if OSInfo.IS_LINUX:
            self.makedirs(self.config.otherToolsDir / "bin")
            # NOTE: 2.0.2 won't work for me
            runCmd("wget", "https://github.com/ocaml/opam/releases/download/2.0.6/opam-2.0.6-x86_64-linux", "-O",
                   self.config.otherToolsDir / "bin/opam")
            # Make it executable
            if not self.config.pretend:
                (self.config.otherToolsDir / "bin/opam").chmod(0o755)
        else:
            self.fatal("This target is only implement for Linux x86_64, for others operating systems you will have"
                       " to install opam 2.0 manually")


class BuildBubbleWrap(AutotoolsProject):
    project_name = "bubblewrap"
    repository = GitRepository("https://github.com/projectatomic/bubblewrap")
    native_install_dir = DefaultInstallDir.BOOTSTRAP_TOOLS

    def __init__(self, config):
        super().__init__(config)
        self._addRequiredSystemHeader("sys/capability.h", apt="libcap-dev")
        self.configureCommand = self.sourceDir / "autogen.sh"
        self.configureArgs.append("--with-bash-completion-dir=no")


class ProjectUsingOpam(OpamMixin, Project):
    doNotAddToTargets = True


REMS_OPAM_REPO = "https://github.com/rems-project/opam-repository.git"


class BuildSailFromOpam(ProjectUsingOpam):
    target = "sail"
    project_name = "sail"
    repository = GitRepository("https://github.com/rems-project/sail", default_branch="sail2")
    native_install_dir = DefaultInstallDir.CHERI_SDK
    build_in_source_dir = True  # Cannot build out-of-source
    make_kind = MakeCommandKind.GnuMake

    def __init__(self, config: CheriConfig):
        super().__init__(config)
        self.add_required_system_tool("z3", homebrew="z3 --without-python@2 --with-python")

    @classmethod
    def setup_config_options(cls, **kwargs):
        super().setup_config_options(**kwargs)
        cls.use_git_version = cls.add_bool_option("use-git-version", show_help=False,
            help="Install sail from github instead of using the latest released version")

    def update(self):
        if not self.use_git_version:
            return
        super().update()

    def compile(self, **kwargs):
        pass

    def install(self, **kwargs):
        # self.run_command_in_ocaml_env(["env"])
        repos = self.run_opam_cmd("repository", "list", captureOutput=True)
        if REMS_OPAM_REPO not in repos.stdout.decode("utf-8"):
            self.run_opam_cmd("repository", "add", "rems", REMS_OPAM_REPO)
        else:
            self.info("REMS opam repo already added")

        if not self.config.skipUpdate:
            self.run_opam_cmd("update")

        if self.config.clean or True:
            if not self.config.clean:
                self.info("opam --destdir does not work with update -> doing full reinstall instead of update")
            self.run_opam_cmd("uninstall", "--verbose", "sail", "--destdir=" + str(self.config.cheri_sdk_dir / "sailprefix"))
            self.run_opam_cmd("uninstall", "--verbose", "sail")

        # ensure sail isn't pinned
        self.run_opam_cmd("pin", "remove", "sail", "--no-action")
        if self.use_git_version:
            # Force installation from latest git (pin repo now, but pass --no-action since we need to install with
            # --destdir)
            self.run_opam_cmd("pin", "add", "sail", self.sourceDir, "--verbose", "--no-action")
        try:
            self.run_opam_cmd("install", "-y", "--verbose", "sail", "--destdir=" + str(self.config.cheri_sdk_dir))
            # I bet this will not work as intended... Probably better to just uninstall and reinstall
            self.run_opam_cmd("upgrade", "-y", "--verbose", "sail")  # "--destdir=" + str(self.config.cheri_sdk_dir))
        finally:
            # reset the pin status even if the pinning failed
            self.run_opam_cmd("pin", "remove", "sail", "--no-action")

        # noinspection PyUnreachableCode
        if False:
            self.run_opam_cmd("install", "-y", "--verbose", "sail")
            opamroot_sail_binary = self.opamroot / "4.06.0/bin/sail"
            runCmd(opamroot_sail_binary, "-v")
            self.createSymlink(opamroot_sail_binary, self.config.cheri_sdk_bindir / opamroot_sail_binary.name)


target_manager.add_target_alias("sail-from-opam", "sail", deprecated=True)


class BuildSailCheriMips(ProjectUsingOpam):
    target = "sail-cheri-mips"
    project_name = "sail-cheri-mips"
    repository = GitRepository("https://github.com/CTSRD-CHERI/sail-cheri-mips")
    dependencies = ["sail"]
    native_install_dir = DefaultInstallDir.CHERI_SDK
    build_in_source_dir = True  # Cannot build out-of-source
    make_kind = MakeCommandKind.GnuMake

    def __init__(self, config):
        super().__init__(config)
        # not always found in /usr/include
        # self._addRequiredSystemHeader("gmp.h", homebrew="gmp", apt="libgmp-dev")

    @classmethod
    def setup_config_options(cls, **kwargs):
        super().setup_config_options(**kwargs)
        cls.with_trace_support = cls.add_bool_option("trace-support", show_help=True,
                                                   help="Build sail-cheri-mips simulators with tracing support (they "
                                                        "will be slow but the traces are useful to debug failing "
                                                        "tests)")

    def compile(self, **kwargs):
        if self.with_trace_support:
            self.make_args.set(TRACE="yes")
        cmd = [self.make_args.command, self.config.makeJFlag, "all"] + self.make_args.all_commandline_args
        self.run_command_in_ocaml_env(cmd, cwd=self.sourceDir)

    def install(self, **kwargs):
        self.make_args.set(INSTALL_DIR=self.config.cheri_sdk_dir)
        self.run_make("install")


class RunSailShell(OpamMixin, SimpleProject):
    target = "sail-env"
    repository = GitRepository("https://github.com/CTSRD-CHERI/sail-cheri-mips")
    dependencies = ["sail"]
    native_install_dir = DefaultInstallDir.CHERI_SDK

    def process(self):
        shell = os.getenv("SHELL", "bash")
        self.info("Starting sail shell (using {})... ".format(shell))
        import subprocess
        try:
            with setEnv(PATH=str(self.config.cheri_sdk_bindir) + ":" + os.getenv("PATH", ""),
                        PS1="SAIL ENV:\\w> "):
                self.run_cmd("which", "sail")
                self.run_command_in_ocaml_env([shell, "--verbose", "--norc", "-i"], cwd=os.getcwd())
        except subprocess.CalledProcessError as e:
            if e.returncode == 130:
                return  # User pressed Ctrl+D to exit shell, don't print an error
            raise


class BuildSailRISCV(ProjectUsingOpam):
    target = "sail-riscv"
    project_name = "sail-riscv"
    repository = GitRepository("https://github.com/rems-project/sail-riscv")
    dependencies = ["sail"]
    native_install_dir = DefaultInstallDir.CHERI_SDK
    build_in_source_dir = True  # Cannot build out-of-source
    make_kind = MakeCommandKind.GnuMake

    def __init__(self, config):
        super().__init__(config)
        self._addRequiredSystemHeader("gmp.h", homebrew="gmp", apt="libgmp-dev")

    @classmethod
    def setup_config_options(cls, **kwargs):
        super().setup_config_options(**kwargs)
        cls.with_trace_support = cls.add_bool_option("trace-support", show_help=True,
                                                   help="Build sail-cheri-mips simulators with tracing support (they "
                                                        "will be slow but"
                                                        "the traces are useful to debug failing tests)")

    def compile(self, **kwargs):
        if self.with_trace_support:
            self.make_args.set(TRACE="yes")
        cmd = [self.make_args.command, self.config.makeJFlag, "opam-build"] + self.make_args.all_commandline_args
        self.run_command_in_ocaml_env(cmd, cwd=self.sourceDir)

    def install(self, **kwargs):
        self.make_args.set(INSTALL_DIR=self.config.cheri_sdk_dir)
        # self.run_make("install")
        self.info("NO INSTALL TARGET YET")


class BuildSailCheriRISCV(ProjectUsingOpam):
    target = "sail-cheri-riscv"
    project_name = "sail-cheri-riscv"
    repository = GitRepository("https://github.com/CTSRD-CHERI/sail-cheri-riscv")
    dependencies = ["sail"]
    native_install_dir = DefaultInstallDir.CHERI_SDK
    build_in_source_dir = True  # Cannot build out-of-source
    make_kind = MakeCommandKind.GnuMake

    def __init__(self, config):
        super().__init__(config)
        self._addRequiredSystemHeader("gmp.h", homebrew="gmp", apt="libgmp-dev")

    @classmethod
    def setup_config_options(cls, **kwargs):
        super().setup_config_options(**kwargs)
        cls.with_trace_support = cls.add_bool_option("trace-support", show_help=True,
                                                   help="Build sail-cheri-mips simulators with tracing support (they "
                                                        "will be slow but the traces are useful to debug failing "
                                                        "tests)")

    def compile(self, **kwargs):
        if self.with_trace_support:
            self.make_args.set(TRACE="yes")
        cmd = [self.make_args.command, self.config.makeJFlag, "opam-build"] + self.make_args.all_commandline_args
        self.run_command_in_ocaml_env(cmd, cwd=self.sourceDir)

    def install(self, **kwargs):
        self.make_args.set(INSTALL_DIR=self.config.cheri_sdk_dir)
        # self.run_make("install")
        self.info("NO INSTALL TARGET YET")


# Old way of installing sail:
class OcamlProject(OpamMixin, Project):
    doNotAddToTargets = True
    native_install_dir = DefaultInstallDir.CHERI_SDK
    build_in_source_dir = True
    make_kind = MakeCommandKind.GnuMake
    needed_ocaml_packages = ["ocamlbuild"]

    def __init__(self, config: CheriConfig):
        super().__init__(config)
        # The homebrew version of ocaml doesn't seem compatible -> suggest --without-ocaml --without-aspcud
        # This avoids pulling in incompatible ocaml and the python@2 formula
        # self.add_required_system_tool("opam", homebrew="opam --without-ocaml --without-camlp4 --without-aspcud")
        self.add_required_system_tool("opam",
                                   homebrew="Installing with hombrew generates a broken ocaml env, use this instead: "
                                            "`wget https://raw.github.com/ocaml/opam/master/shell/opam_installer.sh "
                                            "-O - | sh -s /usr/local/bin`")

    def check_system_dependencies(self):
        super().check_system_dependencies()
        for pkg in self.needed_ocaml_packages:
            try:
                self.run_in_ocaml_env("ocamlfind query " + shlex.quote(pkg), cwd="/", print_verbose_only=True)
            except CalledProcessError:
                instrs = "Try running `" + self._opam_cmd_str("install", _add_switch=False) + pkg + "`"
                self.dependency_error("missing opam package " + pkg, install_instructions=instrs)

    def install(self, **kwargs):
        pass

    def process(self):
        try:
            # This is run before cloning so the source dir might not exist -> set CWD to /
            self.run_in_ocaml_env("ocamlfind ocamlc -where", cwd="/", print_verbose_only=True)
        except CalledProcessError as e:
            self.warning(e)
            self.warning("stderr was:", e.stderr)
            self.dependency_error(
                "OCaml env seems to be messed up. Note: On MacOS homebrew OCaml is not installed correctly. Try "
                "installing it with opam instead:", install_instructions="Try running `" + self._opam_cmd_str("update",
                    _add_switch=False) + " && " + self._opam_cmd_str("switch", _add_switch=False) + " 4.06.0`")
        super().process()


class BuildSailFromSource(OcamlProject):
    target = "sail-from-source"
    repository = GitRepository("https://github.com/rems-project/sail", default_branch="sail2")
    dependencies = ["lem", "ott", "linksem"]
    needed_ocaml_packages = OcamlProject.needed_ocaml_packages + ["zarith", "lem", "linksem"]

    # TODO: `opam install linenoise` for isail?

    def __init__(self, config: CheriConfig):
        super().__init__(config)
        self.add_required_system_tool("z3", homebrew="z3 --without-python@2 --with-python")

    def check_system_dependencies(self):
        super().check_system_dependencies()
        try:
            # opam and ocamlfind don't agree for menhir
            self.run_in_ocaml_env("ocamlfind query menhirLib", cwd="/", print_verbose_only=True)
        except CalledProcessError:
            self.dependency_error("missing opam package menhirLib",
                                 install_instructions="Try running `opam install menhir`")

    def compile(self, **kwargs):
        self.run_in_ocaml_env("""
make
make -C mips mips mips_c
make -C cheri cheri cheri_c
make -C cheri cheri128 cheri128_c""")

    def process(self):
        lemdir = BuildLem.getSourceDir(self)
        ottdir = BuildOtt.getSourceDir(self)
        linksemdir = BuildLinksem.getSourceDir(self)
        with setEnv(LEMLIB=lemdir / "library",
                    PATH="{}:{}:".format(ottdir / "bin", lemdir / "bin") + os.environ["PATH"],
                    OCAMLPATH="{}:{}".format(lemdir / "ocaml-lib/local", linksemdir / "src/local")):
            super().process()


class BuildLem(OcamlProject):
    repository = GitRepository("https://github.com/rems-project/lem")
    needed_ocaml_packages = OcamlProject.needed_ocaml_packages + ["zarith"]

    def compile(self, **kwargs):
        # Note: this all breaks on MacOS if ocamlfind is installed via opam
        self.run_in_ocaml_env("make && make -C ocaml-lib local-install")

    def install(self, **kwargs):
        pass


class BuildOtt(OcamlProject):
    repository = GitRepository("https://github.com/ott-lang/ott")

    def compile(self, **kwargs):
        self.run_in_ocaml_env("make")


class BuildLinksem(OcamlProject):
    repository = GitRepository("https://github.com/rems-project/linksem")
    dependencies = ["lem", "ott"]

    def compile(self, **kwargs):
        self.run_in_ocaml_env("""
make USE_OCAMLBUILD=false
make -C src USE_OCAMLBUILD=false local-install
        """)

    def process(self):
        lemdir = BuildLem.getSourceDir(self)
        ottdir = BuildOtt.getSourceDir(self)
        # linksemdir = BuildLinkSem.getSourceDir(self)
        with setEnv(LEMLIB=lemdir / "library",
                    PATH="{}:{}:".format(ottdir / "bin", lemdir / "bin") + os.environ["PATH"],
                    OCAMLPATH=lemdir / "ocaml-lib/local"):
            super().process()
