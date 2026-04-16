default: check

clean:
    rm -rf build/ dist/ src/*.egg-info

test:
    uv run python -m pytest tests/ -v

lint:
    uvx ruff check .

format:
    uvx ruff format .

fix:
    uvx ruff check --fix .

typecheck:
    uv run mypy .

check: clean format fix typecheck test

bump part="patch":
    #!/usr/bin/env bash
    current=$(grep '^version' pyproject.toml | sed 's/.*"\(.*\)"/\1/')
    IFS='.' read -r major minor patch <<< "$current"
    case "{{part}}" in
    major) major=$((major + 1)); minor=0; patch=0 ;;
    minor) minor=$((minor + 1)); patch=0 ;;
    patch) patch=$((patch + 1)) ;;
    *)
        echo "[error] invalid part: {{part}} (expected major, minor, or patch)" >&2
        exit 1
        ;;
    esac
    new="${major}.${minor}.${patch}"
    sd '^version = ".*"' "version = \"${new}\"" pyproject.toml
    echo "${current} -> ${new}"

install shell=`basename "$SHELL"`: check
    uv tool install --force --reinstall .
    just install-completions {{shell}}

install-completions shell=`basename "$SHELL"`:
    #!/usr/bin/env bash
    case "{{shell}}" in
    fish)
        mkdir -p ~/.config/fish/completions
        vtt completions fish > ~/.config/fish/completions/vtt.fish
        ;;
    zsh)
        mkdir -p ~/.zsh/completions
        vtt completions zsh > ~/.zsh/completions/_vtt
        ;;
    bash)
        mkdir -p ~/.local/share/bash-completion/completions
        vtt completions bash > ~/.local/share/bash-completion/completions/vtt
        ;;
    *)
        echo "[error] unsupported shell: {{shell}}" >&2
        exit 1
        ;;
    esac
    echo "installed vtt + {{shell}} completions"
