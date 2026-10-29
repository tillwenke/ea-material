# Build all posters into pdf/ with LuaLaTeX.
POSTERS := $(wildcard posters/*.tex)
PDFS    := $(patsubst posters/%.tex,pdf/%.pdf,$(POSTERS))

all: $(PDFS)

pdf/%.pdf: posters/%.tex posters/common/*.tex posters/common/qr/*.tex
	@mkdir -p build pdf
	cd posters && latexmk -lualatex -interaction=nonstopmode -halt-on-error -outdir=../build $*.tex
	cp build/$*.pdf $@

previews: all
	@mkdir -p previews
	for f in pdf/*.pdf; do pdftoppm -png -r 50 -singlefile $$f previews/$$(basename $$f .pdf); done

# IBIS screen ad for one Luma event: make ibis URL=https://luma.com/abcd1234 [ORG=zais]
ibis:
	python3 scripts/ibis.py $(URL) $(if $(ORG),--org $(ORG))

clean:
	rm -rf build

.PHONY: all clean previews ibis
