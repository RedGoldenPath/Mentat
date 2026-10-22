#!/bin/zsh
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd /Users/raphael/Everything/mentat/app || exit 1

prev=0; prevt=$(date +%s); rate="—"
while true; do
  LOG=$(ls -t corpus/logs/index_fast*.log corpus/logs/index_now.log 2>/dev/null | head -1)
  if pgrep -f "brain.py index" >/dev/null; then running=yes; else running=no; fi
  total=$(find ../books -type f \( -iname '*.md' -o -iname '*.txt' -o -iname '*.pdf' -o -iname '*.epub' -o -iname '*.docx' -o -iname '*.doc' -o -iname '*.mobi' -o -iname '*.html' \) 2>/dev/null | wc -l | tr -d ' ')
  done=$(sqlite3 storage/library.db "SELECT count(DISTINCT CASE WHEN instr(file_path,' · ')>0 THEN substr(file_path,1,instr(file_path,' · ')-1) ELSE file_path END) FROM chunks;" 2>/dev/null)
  chunks=$(sqlite3 storage/library.db "SELECT count(*) FROM chunks;" 2>/dev/null)
  last=$(grep -E '^indexed:|^updated:' "$LOG" 2>/dev/null | tail -1 | sed 's/^indexed: //;s/^updated: //')
  now=$(date +%s); dt=$((now-prevt))
  if [ "$dt" -ge 4 ] && [ "$done" -gt "$prev" ]; then rate=$(( (done-prev)*60/dt )); fi
  if [ "$dt" -ge 4 ]; then prev=$done; prevt=$now; fi

  pct=0; [ "${total:-0}" -gt 0 ] && pct=$(( done*100/total )); [ "$pct" -gt 100 ] && pct=100
  filled=$(( pct*26/100 )); empty=$(( 26-filled ))
  bar=$(printf '█%.0s' {1..$filled})$(printf '░%.0s' {1..$empty})
  remain=$(( total-done ))

  clear
  print -P "%B%F{cyan}════════════════════════════════════════════════════════════════%f%b"
  print -P "        %B%F{yellow}📚   MENTAT IS READING YOUR LIBRARY%b%f"
  print -P "%B%F{cyan}════════════════════════════════════════════════════════════════%f%b"
  echo
  print -P "   ${bar}   %B${pct}%%b"
  echo "   ${done} of ${total} books incorporated  ·  ${remain} to go"
  echo
  print -P "   %F{white}Now working on :%f  ${last:t}"
  print -P "   %F{white}Speed          :%f  ~${rate} books / minute"
  print -P "   %F{white}Searchable now :%f  ${chunks} passages of text"
  echo
  if [ "$running" = "yes" ]; then
    print -P "   %F{green}● Working…%f   you can leave this open. Ctrl-C to close."
  else
    print -P "   %F{green}✓ Finished — your library is up to date.%f"
  fi
  echo
  print -P "   %F{240}updated $(date '+%H:%M:%S')%f"
  sleep 5
done
