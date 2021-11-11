# -
# SPDX-License-Identifier: BSD-2-Clause
#
# Copyright (c) 2020 A. Theodore Markettos
# All rights reserved.
#
# This software was developed by SRI International and the University of
# Cambridge Computer Laboratory (Department of Computer Science and
# Technology) under DARPA contract HR0011-18-C-0016 ("ECATS"), as part of the
# DARPA SSITH research programme.
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

from .crosscompileproject import CheriConfig
from .crosscompileproject import CompilationTargets, CrossCompileAutotoolsProject, DefaultInstallDir, GitRepository


class BuildDeviceModel(CrossCompileAutotoolsProject):
    repository = GitRepository("https://github.com/CTSRD-CHERI/device-model-riscv")
    target = "device-model"
    is_sdk_target = True
    needs_sysroot = False  # We don't need a complete sysroot
    supported_architectures = [CompilationTargets.BAREMETAL_NEWLIB_RISCV64_PURECAP]
    default_install_dir = DefaultInstallDir.ROOTFS_LOCALBASE
    build_in_source_dir = True  # Cannot build out-of-source

    def compile(self, **kwargs):
        self.run_make("purecap")

    def install(self, **kwargs):
        self.install_file(self.build_dir / "obj/device-model-riscv.bin",
                          self.real_install_root_dir / "device-model-riscv.bin")

    def setup(self):
        super().setup()
        self.CC = self.sdk_bindir / "clang"
        objcopy = self.sdk_bindir / "llvm-objcopy"
        self.make_args.env_vars.update({"CC": str(self.CC),
                                        "AS": str(self.CC),
                                        "OBJCOPY": str(objcopy)})
