# Serein shell prompt (Phase-7-completion Section 18).
#
# Lightweight, override-friendly, no framework - a single sourced
# bash function, not a compiled binary or a package with its own
# config DSL. Source this from ~/.bashrc or a system-defaults skeleton
# (Section 24: "system defaults should be override-friendly, user
# config overrides system defaults" - this file is never sourced
# automatically by anything that would overwrite a user's own existing
# ~/.bashrc customization).
#
# Format:
#   clean:  ~/Projects/Serein  main >
#   dirty:  ~/Projects/Serein  main* >
#   error:  ~/Projects/Serein  main ! >
#
# Design constraints actually honored:
#   - one `git` invocation per prompt render at most (never a blocking
#     network call - `git status`/`diff --quiet` are local-only)
#   - skips the whole git segment instantly outside a git repo
#     (`git rev-parse --is-inside-work-tree` is the one fast check)
#   - works without Nerd Fonts - plain ASCII only, no icons
#   - bash only for now (this repo's own dev/CI shell) - zsh support
#     is a scoped-out follow-up, not silently assumed
#
# Future workspace prefixes (AI/DEV/SEC - Section 18's own "Future
# workspace prefixes may be... But only wire real states") are
# deliberately NOT implemented here: no per-directory workspace/Focus
# assignment exists yet, and shelling out to a Python Focus-state
# reader on every single prompt render would violate this same
# section's "no huge subprocess count" - a future change should read
# a tiny cached indicator file instead, never invoke a subprocess
# per-prompt.

_serein_prompt_git_info() {
    git rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
    local branch
    branch=$(git symbolic-ref --quiet --short HEAD 2>/dev/null)
    if [ -z "$branch" ]; then
        branch=$(git rev-parse --short HEAD 2>/dev/null)
    fi
    [ -n "$branch" ] || return 0
    local dirty=""
    git diff --quiet --ignore-submodules HEAD -- 2>/dev/null || dirty="*"
    printf '%s%s' "$branch" "$dirty"
}

serein_prompt() {
    local exit_code=$?
    local cwd
    cwd=$(pwd)
    case "$cwd" in
        "$HOME") cwd="~" ;;
        "$HOME"/*) cwd="~${cwd#"$HOME"}" ;;
    esac

    local git_info
    git_info=$(_serein_prompt_git_info)

    local error_marker=""
    if [ "$exit_code" -ne 0 ]; then
        error_marker=" !"
    fi

    if [ -n "$git_info" ]; then
        PS1="${cwd}  ${git_info}${error_marker} > "
    else
        PS1="${cwd}${error_marker} > "
    fi
}

PROMPT_COMMAND=serein_prompt
