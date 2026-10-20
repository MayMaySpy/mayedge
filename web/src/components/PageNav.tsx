import { ArrowLeftIcon } from "lucide-react";
import { JOURNAL_PATH, PORTFOLIO_PATH, readSymbol, toPath } from "@/lib/deskRoute";

const PAGES = [
  { name: "Portfolio", path: PORTFOLIO_PATH },
  { name: "Journal", path: JOURNAL_PATH },
] as const;

type Page = (typeof PAGES)[number]["name"];

/** The pages' shared nav: back to the desk, then each page; the current one is the title. */
export function PageNav({ current }: { current: Page }) {
  return (
    <nav aria-label="Pages" className="flex items-center gap-3">
      <a
        href={toPath(readSymbol("/"))}
        className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
      >
        <ArrowLeftIcon className="size-3.5" aria-hidden />
        Desk
      </a>
      {PAGES.map((page) =>
        page.name === current ? (
          <h1 key={page.name} className="text-lg font-medium">
            {page.name}
          </h1>
        ) : (
          <a key={page.name} href={page.path} className="text-muted-foreground hover:text-foreground">
            {page.name}
          </a>
        ),
      )}
    </nav>
  );
}
