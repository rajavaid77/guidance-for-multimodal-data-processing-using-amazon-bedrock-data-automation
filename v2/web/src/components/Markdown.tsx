import { Fragment, type ReactElement } from "react";

function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <b key={i}>{part.slice(2, -2)}</b> : <Fragment key={i}>{part}</Fragment>,
  );
}

/** Renders the agent summary's light markdown (paragraphs, "- " bullets, **bold**) as React elements. */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactElement[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) blocks.push(<ul key={blocks.length}>{bullets.map((b, i) => <li key={i}>{inline(b)}</li>)}</ul>);
    bullets = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (/^[-*•] /.test(line)) bullets.push(line.slice(2));
    else {
      flush();
      if (line) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
    }
  }
  flush();
  return <div className="md">{blocks}</div>;
}
