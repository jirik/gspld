#!/bin/bash

echo "Deleting Python cache files"
find . | grep -E "(\.pytest_cache|__pycache__|\.pyc|\.pyo$)" | xargs rm -rf
