#!/bin/sh
set -eu

cargo install --path crates/tracejit-cli
echo "Installed. On Linux x86_64, run: tracejit doctor"

