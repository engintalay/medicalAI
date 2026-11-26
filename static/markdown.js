/* Küçük, güvenli Markdown görüntüleyici — ham HTML çalıştırmaz. */
(function () {
    'use strict';

    function escapeHtml(value) {
        return String(value || '').replace(/[&<>"']/g, function (ch) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
        });
    }

    function inline(text) {
        let html = escapeHtml(text);
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        html = html.replace(
            /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
        );
        return html;
    }

    function cells(line) {
        return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (cell) {
            return cell.trim();
        });
    }

    function isTableLine(line) {
        return /^\s*\|.*\|\s*$/.test(line);
    }

    function isSeparator(line) {
        return isTableLine(line) && cells(line).every(function (cell) {
            return /^:?-{3,}:?$/.test(cell.replace(/\s/g, ''));
        });
    }

    function startsBlock(line, next) {
        return !line.trim() || /^(#{1,6})\s+/.test(line) ||
            /^\s*([-*+]|\d+[.)])\s+/.test(line) || /^>\s?/.test(line) ||
            /^```/.test(line) || /^\s*([-*_])\1{2,}\s*$/.test(line) ||
            (isTableLine(line) && next !== undefined && isSeparator(next));
    }

    function render(text) {
        const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
        const out = [];
        let paragraph = [];
        let index = 0;

        function flushParagraph() {
            if (!paragraph.length) return;
            out.push('<p>' + paragraph.map(inline).join('<br>') + '</p>');
            paragraph = [];
        }

        while (index < lines.length) {
            const line = lines[index];
            const next = lines[index + 1];

            if (!line.trim()) {
                flushParagraph();
                index += 1;
                continue;
            }

            if (/^```/.test(line)) {
                flushParagraph();
                const language = line.replace(/^```/, '').trim();
                const code = [];
                index += 1;
                while (index < lines.length && !/^```/.test(lines[index])) {
                    code.push(lines[index]);
                    index += 1;
                }
                index += 1;
                out.push('<pre><code' + (language ? ' class="language-' + escapeHtml(language) + '"' : '') +
                    '>' + escapeHtml(code.join('\n')) + '</code></pre>');
                continue;
            }

            const heading = line.match(/^(#{1,6})\s+(.*)$/);
            if (heading) {
                flushParagraph();
                const level = heading[1].length;
                out.push('<h' + level + '>' + inline(heading[2]) + '</h' + level + '>');
                index += 1;
                continue;
            }

            if (isTableLine(line) && next !== undefined && isSeparator(next)) {
                flushParagraph();
                const headers = cells(line);
                index += 2;
                const rows = [];
                while (index < lines.length && isTableLine(lines[index])) {
                    rows.push(cells(lines[index]));
                    index += 1;
                }
                out.push('<div class="markdown-table-wrap"><table><thead><tr>' +
                    headers.map(function (cell) { return '<th>' + inline(cell) + '</th>'; }).join('') +
                    '</tr></thead><tbody>' + rows.map(function (row) {
                        return '<tr>' + headers.map(function (_cell, cellIndex) {
                            return '<td>' + inline(row[cellIndex] || '') + '</td>';
                        }).join('') + '</tr>';
                    }).join('') + '</tbody></table></div>');
                continue;
            }

            const list = line.match(/^\s*([-*+]|\d+[.)])\s+(.*)$/);
            if (list) {
                flushParagraph();
                const ordered = /^\d/.test(list[1]);
                const tag = ordered ? 'ol' : 'ul';
                const items = [];
                while (index < lines.length) {
                    const match = lines[index].match(/^\s*([-*+]|\d+[.)])\s+(.*)$/);
                    if (!match || (/^\d/.test(match[1]) !== ordered)) break;
                    items.push('<li>' + inline(match[2]) + '</li>');
                    index += 1;
                }
                out.push('<' + tag + '>' + items.join('') + '</' + tag + '>');
                continue;
            }

            if (/^>\s?/.test(line)) {
                flushParagraph();
                const quote = [];
                while (index < lines.length && /^>\s?/.test(lines[index])) {
                    quote.push(lines[index].replace(/^>\s?/, ''));
                    index += 1;
                }
                out.push('<blockquote>' + quote.map(inline).join('<br>') + '</blockquote>');
                continue;
            }

            if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
                flushParagraph();
                out.push('<hr>');
                index += 1;
                continue;
            }

            paragraph.push(line);
            index += 1;
            if (lines[index] !== undefined && startsBlock(lines[index], lines[index + 1])) {
                flushParagraph();
            }
        }
        flushParagraph();
        return out.join('\n');
    }

    window.MedicalMarkdown = { render: render };
})();
