#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/webhdp-user/webhdp}"
SIF_DIR="${SIF_DIR:-$ROOT/images/sif}"
OUT_JAR="${LOCAL_EDM_VALIDATOR_APP_JAR:-$ROOT/tools/local-edm-validator/app.jar}"
WORK_DIR="${LOCAL_EDM_VALIDATOR_PATCH_WORK_DIR:-$ROOT/tools/build/local-edm-validator-patch}"
MEDIA_JAR="BOOT-INF/lib/metis-media-service-17-SNAPSHOT.jar"
PROCESSOR_CLASS="eu/europeana/metis/mediaprocessing/extraction/AudioVideoProcessor.class"

mkdir -p "$WORK_DIR" "$(dirname "$OUT_JAR")"
rm -rf "$WORK_DIR"/*

singularity exec --cleanenv "$SIF_DIR/local-edm-validator.sif" cat /app.jar >"$WORK_DIR/app.jar"
unzip -p "$WORK_DIR/app.jar" "$MEDIA_JAR" >"$WORK_DIR/metis-media-service.jar"
mkdir -p "$WORK_DIR/classes/$(dirname "$PROCESSOR_CLASS")"
unzip -p "$WORK_DIR/metis-media-service.jar" "$PROCESSOR_CLASS" >"$WORK_DIR/classes/$PROCESSOR_CLASS"

# The upstream startup check parses the ffprobe major version from a brittle
# no-argument command output path. Permit parser result 0 so the validator can
# continue to use the real ffprobe binary for actual media processing.
perl -0777 -pi -e 'use bytes; s/\x15\x04\x05\xA1\x00\x0A/\x15\x04\x03\xA1\x00\x0A/' "$WORK_DIR/classes/$PROCESSOR_CLASS"

(
  cd "$WORK_DIR/classes"
  zip -q "$WORK_DIR/metis-media-service.jar" "$PROCESSOR_CLASS"
)
mkdir -p "$WORK_DIR/app/BOOT-INF/lib"
cp "$WORK_DIR/metis-media-service.jar" "$WORK_DIR/app/$MEDIA_JAR"
(
  cd "$WORK_DIR/app"
  # Spring Boot executable jars require nested dependency jars to be STORED.
  zip -0 -q "$WORK_DIR/app.jar" "$MEDIA_JAR"
)

cp "$WORK_DIR/app.jar" "$OUT_JAR"
javap -classpath "$WORK_DIR/metis-media-service.jar" -c -p \
  eu.europeana.metis.mediaprocessing.extraction.AudioVideoProcessor \
  | sed -n '/discoverFfprobeCommand/,/resourceHasContent/p' \
  | grep -E 'iconst_0|if_icmplt|bipush'
echo "$OUT_JAR"
