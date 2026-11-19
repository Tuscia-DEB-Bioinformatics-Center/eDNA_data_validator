#!/usr/bin/env bash
# controllo_server.sh - check that the FASTQ files listed in TSV tables exist on this server.
#
# Usage:  bash controllo_server.sh [FOLDER_OR_TSV_FILE ...]
#
# With no argument it checks every .tsv file in the current folder. The script only reads:
# it never modifies, moves or deletes anything. It needs nothing but bash and awk.
# Exit code: 0 = all files found, 1 = some file missing, 2 = the check could not run.

# Awk program: prints "<column><TAB><path><TAB><rows>" for each distinct FASTQ path of a TSV.
# Prints a single "NOCOLUMNS" line when the table has no File / File_forward / File_reverse column.
AWK_PROGRAM='
function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
function flush(key) {
    if (start[key] != "") {
        text[key] = text[key] (text[key] == "" ? "" : ", ") \
            (start[key] == last[key] ? start[key] : start[key] "-" last[key])
    }
}
BEGIN { FS = "\t"; ncols = 0; n = 0 }
NR == 1 {
    for (i = 1; i <= NF; i++) col[trim($i)] = i
    if ("File_forward" in col) names[++ncols] = "File_forward"
    if ("File_reverse" in col) names[++ncols] = "File_reverse"
    if (ncols == 0 && "File" in col) names[++ncols] = "File"
    next
}
{
    for (k = 1; k <= ncols; k++) {
        value = trim($(col[names[k]]))
        if (value == "") continue
        key = k SUBSEP value
        if (!(key in seen)) {
            seen[key] = 1; order[++n] = key; kcol[n] = k; kval[n] = value
            start[key] = NR; last[key] = NR; text[key] = ""
        } else if (NR == last[key] + 1) {
            last[key] = NR
        } else {
            flush(key); start[key] = NR; last[key] = NR
        }
    }
}
END {
    if (ncols == 0) { print "NOCOLUMNS"; exit }
    for (i = 1; i <= n; i++) {
        key = order[i]; flush(key)
        printf "%s\t%s\t%s\n", names[kcol[i]], kval[i], text[key]
    }
}
'

total_tables=0
failed_tables=()

# check_table FILE: prints the result for one TSV and records it in the totals.
check_table() {
    local file=$1 name checked=0 missing=0 detail="" data line col path rows
    name=$(basename "$file")
    total_tables=$((total_tables + 1))

    if [ ! -r "$file" ]; then
        echo "$name - PROBLEMA: il file non si può leggere."
        failed_tables+=("$name")
        return
    fi
    # Remove Windows line endings and a possible byte order mark before parsing.
    data=$(tr -d '\r' < "$file" | sed '1s/^\xEF\xBB\xBF//' | awk "$AWK_PROGRAM")
    if [ -z "$data" ] || [ "$data" = "NOCOLUMNS" ]; then
        echo "$name - PROBLEMA: non trovo le colonne File_forward / File_reverse / File nella riga 1."
        failed_tables+=("$name")
        return
    fi

    while IFS=$'\t' read -r col path rows; do
        checked=$((checked + 1))
        if [ "${path#/}" = "$path" ]; then
            missing=$((missing + 1))
            detail+="  PERCORSO NON ASSOLUTO  $path  (colonna $col, righe $rows)"$'\n'
        elif [ ! -f "$path" ]; then
            missing=$((missing + 1))
            detail+="  E17 MANCA  $path  (colonna $col, righe $rows)"$'\n'
        fi
    done <<< "$data"

    if [ "$missing" -eq 0 ]; then
        echo "$name - OK: tutti i file ($checked) sono presenti sul server."
    else
        echo "$name - PROBLEMI: $missing file su $checked non trovati sul server"
        printf '%s' "$detail"
        failed_tables+=("$name")
    fi
}

# Collect the TSV files: files given as arguments, or every .tsv inside the given folders.
files=()
for target in "${@:-.}"; do
    if [ -d "$target" ]; then
        while IFS= read -r found; do
            files+=("$found")
        done < <(find "$target" -maxdepth 1 -type f -iname '*.tsv' | sort)
    elif [ -f "$target" ]; then
        files+=("$target")
    else
        echo "File o cartella non trovati: $target" >&2
        exit 2
    fi
done
if [ "${#files[@]}" -eq 0 ]; then
    echo "Nessun file .tsv trovato. Metti i TSV nella stessa cartella dello script, oppure indica la cartella: bash controllo_server.sh CARTELLA" >&2
    exit 2
fi

for file in "${files[@]}"; do
    check_table "$file"
done

ok=$((total_tables - ${#failed_tables[@]}))
echo
label="tabelle controllate"
[ "$total_tables" -eq 1 ] && label="tabella controllata"
echo "RIEPILOGO: $total_tables $label, $ok OK, ${#failed_tables[@]} con problemi."
if [ "${#failed_tables[@]}" -gt 0 ]; then
    echo "Tabelle da controllare: $(IFS=,; echo "${failed_tables[*]}" | sed 's/,/, /g')"
    echo "Cosa fare: verificare sul server che i file mancanti esistano (comando ls con il percorso indicato) e correggere il percorso nella tabella, oppure ripristinare il file."
    exit 1
fi
echo "Tutti i file indicati nelle tabelle sono presenti sul server."
