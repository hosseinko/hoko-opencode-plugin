#!/usr/bin/env python3
"""Create a Go module layout: library, cli or service.

    go_scaffold.py <library|cli|service> <module-path> <target-dir> [--dry-run]

When `go` is on PATH the module is initialised with `go mod init`; otherwise a
minimal go.mod is written and the script says so. A non-empty target is refused.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

LAYOUTS = ("library", "cli", "service")

GOLANGCI = """version: "2"

linters:
  default: standard
  enable:
    - bodyclose
    - contextcheck
    - copyloopvar
    - errorlint
    - modernize
    - noctx

formatters:
  enable:
    - gofmt
    - gofumpt
    - gci
"""

CI = """name: ci

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-go@v7
        with:
          go-version: stable
      - run: go build ./...
      - run: go vet ./...
      - uses: golangci/golangci-lint-action@v9
      - run: go test -race -coverprofile=coverage.out -covermode=atomic ./...
      - run: go run golang.org/x/vuln/cmd/govulncheck@latest ./...
"""

GOMOD = """module __MODULE__

go 1.27.0
"""

README = """# __MODULE__

A Go __LAYOUT__ module.
"""

DOC_GO = """// Package __PKG__ is the module's importable package.
package __PKG__
"""

PKG_GO = """package __PKG__

func Hello() string {
	return "hello"
}
"""

PKG_TEST = """package __PKG__

import "testing"

func TestHello(t *testing.T) {
	if got, want := Hello(), "hello"; got != want {
		t.Fatalf("Hello() = %q, want %q", got, want)
	}
}
"""

CLI_MAIN = """package main

import (
	"fmt"
	"os"

	"__MODULE__/internal/__PKG__"
)

func main() {
	if err := __PKG__.Run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
"""

CLI_RUN = """package __PKG__

func Run(args []string) error {
	_ = args
	return nil
}
"""

CLI_RUN_TEST = """package __PKG__

import "testing"

func TestRun(t *testing.T) {
	if err := Run(nil); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
}
"""

MAKEFILE = """.PHONY: build test lint

build:
	go build ./...

test:
	go test -race ./...

lint:
	golangci-lint run
"""

SERVICE_MAIN = """package main

import (
	"context"
	"errors"
	"log/slog"
	nethttp "net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"__MODULE__/internal/__PKG__/config"
	apihttp "__MODULE__/internal/__PKG__/http"
)

func main() {
	if err := run(); err != nil {
		slog.Error("server failed", "err", err)
		os.Exit(1)
	}
}

func run() error {
	cfg := config.Load()
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	server := &nethttp.Server{
		Addr:              cfg.Addr,
		Handler:           apihttp.New(logger),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      15 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	serveErr := make(chan error, 1)
	go func() {
		logger.Info("listening", "addr", cfg.Addr)
		serveErr <- server.ListenAndServe()
	}()

	select {
	case err := <-serveErr:
		if err != nil && !errors.Is(err, nethttp.ErrServerClosed) {
			return err
		}
		return nil
	case <-ctx.Done():
	}

	logger.Info("shutting down")
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		return err
	}
	if err := <-serveErr; err != nil && !errors.Is(err, nethttp.ErrServerClosed) {
		return err
	}
	return nil
}
"""

CONFIG_GO = """package config

import "os"

type Config struct {
	Addr string
}

func Load() Config {
	addr := os.Getenv("ADDR")
	if addr == "" {
		addr = ":8080"
	}
	return Config{Addr: addr}
}
"""

SERVICE_GO = """package service

type Service struct{}

func New() *Service {
	return &Service{}
}
"""

HANDLER_GO = """package http

import (
	"log/slog"
	nethttp "net/http"
	"time"
)

func New(logger *slog.Logger) nethttp.Handler {
	mux := nethttp.NewServeMux()
	mux.HandleFunc("GET /health", health)
	return logRequests(logger, mux)
}

func logRequests(logger *slog.Logger, next nethttp.Handler) nethttp.Handler {
	return nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: nethttp.StatusOK}
		next.ServeHTTP(rec, r)
		logger.Info("request",
			"method", r.Method,
			"path", r.URL.Path,
			"status", rec.status,
			"duration", time.Since(start),
		)
	})
}

type statusRecorder struct {
	nethttp.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(status int) {
	r.status = status
	r.ResponseWriter.WriteHeader(status)
}

func (r *statusRecorder) Unwrap() nethttp.ResponseWriter {
	return r.ResponseWriter
}

func health(w nethttp.ResponseWriter, r *nethttp.Request) {
	w.WriteHeader(nethttp.StatusNoContent)
}
"""

HANDLER_TEST = """package http

import (
	"io"
	"log/slog"
	nethttp "net/http"
	"net/http/httptest"
	"testing"
)

func TestHealth(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	tests := []struct {
		name string
		want int
	}{
		{"ok", nethttp.StatusNoContent},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(nethttp.MethodGet, "/health", nil)
			rec := httptest.NewRecorder()
			New(logger).ServeHTTP(rec, req)
			if rec.Code != tt.want {
				t.Fatalf("status = %d, want %d", rec.Code, tt.want)
			}
		})
	}
}
"""


def package_name(module):
    base = module.rstrip("/").split("/")[-1]
    name = re.sub(r"[^a-z0-9]", "", base.lower())
    if not name or name[0].isdigit():
        return "app"
    return name


def render(template, module, pkg):
    return template.replace("__MODULE__", module).replace("__PKG__", pkg)


def readme(layout, module):
    return README.replace("__MODULE__", module).replace("__LAYOUT__", layout)


def layout_files(layout, module):
    pkg = package_name(module)
    if layout == "library":
        return [
            ("go.mod", render(GOMOD, module, pkg)),
            ("doc.go", render(DOC_GO, module, pkg)),
            (f"{pkg}.go", render(PKG_GO, module, pkg)),
            (f"{pkg}_test.go", render(PKG_TEST, module, pkg)),
            ("README.md", readme(layout, module)),
            (".golangci.yml", GOLANGCI),
            (".github/workflows/ci.yml", CI),
        ]
    if layout == "cli":
        return [
            ("go.mod", render(GOMOD, module, pkg)),
            ("main.go", render(CLI_MAIN, module, pkg)),
            (f"internal/{pkg}/{pkg}.go", render(CLI_RUN, module, pkg)),
            (f"internal/{pkg}/{pkg}_test.go", render(CLI_RUN_TEST, module, pkg)),
            ("README.md", readme(layout, module)),
            ("Makefile", MAKEFILE),
            (".golangci.yml", GOLANGCI),
            (".github/workflows/ci.yml", CI),
        ]
    if layout == "service":
        return [
            ("go.mod", render(GOMOD, module, pkg)),
            (f"cmd/{pkg}/main.go", render(SERVICE_MAIN, module, pkg)),
            (f"internal/{pkg}/config/config.go", CONFIG_GO),
            (f"internal/{pkg}/service/service.go", SERVICE_GO),
            (f"internal/{pkg}/http/handler.go", HANDLER_GO),
            (f"internal/{pkg}/http/handler_test.go", HANDLER_TEST),
            ("README.md", readme(layout, module)),
            (".golangci.yml", GOLANGCI),
            (".github/workflows/ci.yml", CI),
        ]
    raise ValueError(layout)


def create(layout, module, target, dry_run=False):
    target = Path(target)
    if layout not in LAYOUTS:
        print(f"unknown layout: {layout}", file=sys.stderr)
        print("valid layouts: " + ", ".join(LAYOUTS), file=sys.stderr)
        return 2
    files = layout_files(layout, module)
    if dry_run:
        for rel, _ in files:
            print(rel)
        return 0
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        print(f"refusing to write into a non-empty target: {target}", file=sys.stderr)
        return 1
    go = shutil.which("go")
    target.mkdir(parents=True, exist_ok=True)
    for rel, content in files:
        if rel == "go.mod" and go is not None:
            continue
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    if go is not None:
        result = subprocess.run([go, "mod", "init", module], cwd=str(target),
                                capture_output=True, text=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")
        if result.returncode != 0:
            print("failed: go mod init", file=sys.stderr)
            return 1
    else:
        print("go — not installed; wrote a minimal go.mod")
    print(f"created {layout} layout in {target}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create a Go module layout.")
    parser.add_argument("layout", choices=LAYOUTS)
    parser.add_argument("module")
    parser.add_argument("target", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="print the paths without writing")
    args = parser.parse_args(argv)
    return create(args.layout, args.module, args.target, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
