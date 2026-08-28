# Preceptor — dev tasks. No build step; this repo is a bundle, not a package.

MODULES := hooks-trajectory-observer hooks-cue-injector tool-preceptor
DIAGRAMS := $(patsubst docs/diagrams/%.dot,docs/diagrams/%.svg,$(wildcard docs/diagrams/*.dot))

.PHONY: help test check diagrams clean all
.DEFAULT_GOAL := help

help:
	@echo "make test      - run all module test suites"
	@echo "make check     - ruff + pyright across all modules"
	@echo "make diagrams  - regenerate SVGs and verify README-scale legibility"
	@echo "make all       - test + check + diagrams"

test:
	@for m in $(MODULES); do \
	  printf '%-30s ' "$$m"; \
	  (cd modules/$$m && uv run --no-project --with pytest --with pytest-asyncio \
	     --with pyyaml pytest tests/ -q 2>&1 | tail -1); \
	done

check:
	@uvx ruff check modules/ probes/
	@uvx ruff format --check modules/ probes/

# The .dot files are the source of truth; SVGs are generated artifacts.
docs/diagrams/%.svg: docs/diagrams/%.dot
	@dot -Tsvg $< -o $@ && echo "rendered $@"

diagrams: $(DIAGRAMS)
	@python3 -c "$$LEGIBILITY_CHECK"

# A diagram that is correct but unreadable at README scale is a broken diagram.
# Width is what kills it: every point of width shrinks the text when GitHub
# scales the SVG down to the content column.
export LEGIBILITY_CHECK
define LEGIBILITY_CHECK
import re, pathlib, sys
bad = []
for p in sorted(pathlib.Path("docs/diagrams").glob("*.svg")):
    s = p.read_text()
    m = re.search(r'width="(\d+)pt" height="(\d+)pt"', s)
    if not m:
        continue
    w = int(m.group(1))
    fonts = [float(x) for x in re.findall(r'font-size="([\d.]+)"', s)]
    if not fonts:
        continue
    px = min(fonts) * (900 / w) * (96 / 72)
    ok = px >= 9.0
    print(f"{p.name:20s} {w}pt wide  min text ~{px:4.1f}px at 900px  {'OK' if ok else 'TOO SMALL'}")
    if not ok:
        bad.append(p.name)
if bad:
    print("\nShorten labels or drop legend nodes in: " + ", ".join(bad))
    sys.exit(1)
print("\nall diagrams legible at README scale")
endef

all: test check diagrams

clean:
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -name .pytest_cache -o -name .ruff_cache -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@find . -name .DS_Store -delete 2>/dev/null || true
	@echo "cleaned"
