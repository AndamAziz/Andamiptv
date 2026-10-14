# VPS add-channel form

Files deployed to `/var/www/add-channel/` on the VPS (`index.php` form + `add.php` backend).
For movies and series the form needs the English name, an optional Kurdish name and the TMDB id, and writes
`English _ Kurdish {tmdb-ID}` (series: `... {tmdb-ID} - S01E01`). Duplicate TMDB ids are refused.
