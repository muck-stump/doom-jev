{
  description = "doom-jev development shell";

  inputs = {
    # Your system channel is a custom nixpkgs 26.11 build that doesn't
    # exist as an upstream branch, so we track master and pin the Python
    # minor version explicitly below.
    nixpkgs.url = "github:NixOS/nixpkgs/master";
  };

  outputs =
    { self
    , nixpkgs
    }:
    let
      pkgs = nixpkgs.legacyPackages.x86_64-linux;

      # The `vizdoom` pip package ships a prebuilt engine binary that is
      # compiled for generic Linux; NixOS' stub ld refuses to execute it.
      # Building the engine with Nix puts it in the store, so it runs.
      #
      # Only the engine is built here: the Python binding .so inside the
      # pip package is self-contained (auditwheel, vendored boost libs),
      # so we only need to replace the `vizdoom` executable it launches.
      #
      # Source: https://github.com/Farama-Foundation/ViZDoom (tag 1.3.1,
      # same version as the installed pip package).
      vizdoom = pkgs.stdenv.mkDerivation
        {
          pname = "vizdoom";
          version = "1.3.1";

          src = pkgs.fetchFromGitHub {
            owner = "Farama-Foundation";
            repo = "ViZDoom";
            rev = "1.3.1";
            hash = "sha256-1dbEBnqFWAxtPCJSfThS8lmlD/k0eBMJdmYyWtLYEnY=";
          };

          nativeBuildInputs = [ pkgs.cmake pkgs.pkg-config ];
          # nixpkgs replaced classic SDL2 with sdl2-compat (exposed as SDL2)
          buildInputs = [ pkgs.boost pkgs.SDL2 ];

          cmakeFlags = [
            "-DBUILD_ENGINE=ON"
            "-DBUILD_PYTHON=OFF"
            # keep the build lean: no audio backend needed for RL
            "-DNO_OPENAL=ON"
          ];

          # no install() rules in the upstream CMake
          installPhase = ''
            mkdir -p $out/bin
            cp bin/* $out/bin/
          '';

          # no test suite is wired up in the CMake build
          doCheck = false;
        };

      # The prebuilt `vizdoom` pip wheel is compiled for CPython 3.14,
      # so make sure the shell's default python is 3.14 even if
      # nixpkgs' default has moved on.
      python =
        if builtins.hasAttr "python314" pkgs
        then pkgs.python314
        else pkgs.python3;
    in
    {
      devShells.x86_64-linux.default = pkgs.mkShell
        {
          name = "doom-jev";

          packages = [
            python
            pkgs.uv
            vizdoom
            # For rebuilding pygame-ce from source. The pip wheel's SDL2 is built
            # without X11/Wayland video drivers, so it silently falls back to the
            # offscreen driver and never shows a window. Inside `nix develop`:
            #   uv pip install --reinstall --no-binary :all: pygame-ce
            pkgs.pkg-config
            pkgs.SDL2.dev
            pkgs.SDL2_image.dev
            pkgs.SDL2_mixer.dev
            pkgs.SDL2_ttf.dev
            pkgs.freetype.dev
            pkgs.xorg.libX11.dev
            pkgs.portmidi
            pkgs.cmake
            pkgs.ninja
          ];

          shellHook = ''
            # Point the Python package at the Nix-built engine binary.
            # The stub-ld check looks at the resolved (store) path, so a
            # symlink into the Nix store is accepted.
            if [ -d .venv/lib/python3.14/site-packages/vizdoom ]; then
              ln -sf ${vizdoom}/bin/vizdoom .venv/lib/python3.14/site-packages/vizdoom/vizdoom
            fi

            # ViZDoom talks to the engine over POSIX message queues whose max message size is a
            # full screen buffer (~1MB). The kernel default msg_max is
            # 8192, which makes queue creation fail and g.init() return
            # False ("VIZ_MQInit: Failed to open message queues").
            msg_max=$(cat /proc/sys/fs/mqueue/msg_max 2>/dev/null || echo 0)
            if [ "$msg_max" -lt 1048576 ]; then
              echo "warning: fs.mqueue.msg_max is $msg_max (need >= 1048576)."
              echo "         run: sudo sysctl -w fs.mqueue.msg_max=10485760 -w fs.mqueue.msgsize_max=10485760"
              echo "         (permanent: boot.sysctl.\"fs.mqueue.msg_max\" = 10485760; in your NixOS config)"
            fi

            export PS1="(doom-jev) $PS1"
          '';
        };
    };
}
