#!/bin/sh
# Usage: indexer/bench.sh <repo> [runs]
# Builds the release binary, then prints one Markdown table: the median time of a cold build, a
# no-change build, and each query command with --no-update, and the size of the index. If the
# sqlite3 program has the dbstat table, it also prints the size of each table and index.
#
# The script needs cargo, awk, sort, and time. It uses git, if it is on PATH, to find a source file.
# Set BENCH_NAME, BENCH_WORDS, or BENCH_PATH to change the arguments of the queries. A query
# sample is the mean of QUERY_BATCH runs, because `time -p` has a resolution of 10 ms.
set -eu

repo=${1:?usage: bench.sh <repo> [runs]}
runs=${2:-10}
QUERY_BATCH=10
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$repo" && pwd)

(cd "$here" && cargo build --release --locked --quiet)
bin=$here/target/release/stone-index
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
db=$work/index.db

name=${BENCH_NAME:-main}
words=${BENCH_WORDS:-error handler}
path=${BENCH_PATH:-$(git -C "$repo" ls-files '*.ts' '*.py' '*.rs' '*.c' '*.cs' '*.js' 2>/dev/null | head -n 1)}

cd "$repo"

# Prints the seconds that one run of the arguments takes. The command output goes to /dev/null
# inside, so the report of `time -p` is the only text. This works with the shell keyword and with
# /usr/bin/time.
seconds() { { time -p sh -c '"$@" >/dev/null 2>&1' sh "$@"; } 2>&1 | awk '/^real/ { print $2 }'; }

# Prints the seconds of a loop of $1 runs of the other arguments.
batch() {
    count=$1
    shift
    start=$(seconds sh -c 'n=$1; shift; while [ "$n" -gt 0 ]; do "$@" >/dev/null 2>&1; n=$((n - 1)); done' sh "$count" "$@")
    echo "$start $count" | awk '{ printf "%.4f\n", $1 / $2 }'
}

# Prints the median of the lines on the standard input.
median() { sort -n | awk '{ v[NR] = $1 } END { if (NR % 2) print v[(NR + 1) / 2]; else print (v[NR / 2] + v[NR / 2 + 1]) / 2 }'; }

# Runs "$@" $runs times with a batch of $1 and prints the median in seconds.
measure() {
    size=$1
    shift
    "$@" >/dev/null 2>&1 || { echo "bench.sh: this command failed: $*" >&2; exit 1; }
    i=0
    while [ "$i" -lt "$runs" ]; do
        batch "$size" "$@"
        i=$((i + 1))
    done | median
}

cold() {
    i=0
    while [ "$i" -lt "$runs" ]; do
        rm -f "$db" "$db-wal" "$db-shm"
        seconds "$bin" build --db "$db"
        i=$((i + 1))
    done | median
}

row() { printf '| %s | %s |\n' "$1" "$2"; }

cold_time=$(cold)
"$bin" build --db "$db" >/dev/null
unchanged=$(measure "$QUERY_BATCH" "$bin" build --db "$db")
bytes=$(cat "$db" "$db-wal" 2>/dev/null | wc -c)
q="$bin"

echo "Repo: $repo, runs: $runs, query name: $name, words: $words, path: $path"
echo
echo '| Measure | Median |'
echo '| --- | --- |'
row 'cold build (s)' "$cold_time"
row 'no-change build (s)' "$unchanged"
row 'find (s)' "$(measure "$QUERY_BATCH" "$q" find "$name" --no-update --db "$db")"
row 'show (s)' "$(measure "$QUERY_BATCH" "$q" show "$name" --no-update --db "$db")"
row 'outline (s)' "$(measure "$QUERY_BATCH" "$q" outline "$path" --no-update --db "$db")"
row 'refs (s)' "$(measure "$QUERY_BATCH" "$q" refs "$path" --no-update --db "$db")"
row 'search (s)' "$(measure "$QUERY_BATCH" "$q" search "$words" --no-update --db "$db")"
row 'index size (MB)' "$(echo "$bytes" | awk '{ printf "%.1f", $1 / 1000000 }')"

if command -v sqlite3 >/dev/null 2>&1 &&
    sqlite3 "$db" 'SELECT count(*) FROM dbstat' >/dev/null 2>&1; then
    echo
    echo '| Table or index | Size (MB) |'
    echo '| --- | --- |'
    sqlite3 -separator ' ' "$db" \
        'SELECT name, sum(pgsize) FROM dbstat GROUP BY name ORDER BY sum(pgsize) DESC' |
        awk '{ printf "| %s | %.1f |\n", $1, $2 / 1000000 }'
fi
