#!/usr/bin/env bash

# This script is used to run Gradle tasks.

# Determine the Java command to use to start the JVM.
if [ -n "$JAVA_HOME" ] ; then
    JAVA_CMD="$JAVA_HOME/bin/java"
else
    JAVA_CMD="java"
fi

# Determine the script directory.
SCRIPT_DIR=$(dirname "$0")

# Execute the Gradle wrapper.
exec "$JAVA_CMD" -jar "$SCRIPT_DIR/gradle/wrapper/gradle-wrapper.jar" "$@"
