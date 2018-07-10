#!/bin/bash

mkdir -p tmp/naturalearth/110m/cultural

ne_110m_cultural=tmp/naturalearth/110m_cultural.zip
if ! [ -f $ne_110m_cultural ]; then
  curl -L -o $ne_110m_cultural "https://www.naturalearthdata.com/http//www.naturalearthdata.com/download/110m/cultural/110m_cultural.zip"
  unzip -q $ne_110m_cultural -d tmp/naturalearth/110m/cultural
fi

ne_110m_cultural_admin_0_countries=tmp/naturalearth/110m/cultural/ne_110m_admin_0_countries.geojson
if ! [ -f $ne_110m_cultural_admin_0_countries ]; then
  curl -L -o $ne_110m_cultural_admin_0_countries "https://github.com/nvkelso/natural-earth-vector/raw/master/geojson/ne_110m_admin_0_countries.geojson"
fi

python3 src/layman/prepare.py && pytest -svv
