import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional

from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


@dataclass(frozen=True)
class Paragraph:
    paragraph_index: int
    text: str


class GoogleDocsClient:
    def __init__(self, docs_service: Any, drive_service: Any):
        self.docs = docs_service
        self.drive = drive_service

    @staticmethod
    def from_env() -> "GoogleDocsClient":
        """
        Auth options:
          1) Service account (best for automation):
             - Set GOOGLE_SERVICE_ACCOUNT_FILE to the JSON key file path
          2) OAuth client secret (easy for local dev):
             - Set GOOGLE_OAUTH_CLIENT_SECRET_FILE to OAuth client secret JSON
        """
        sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        oauth_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_FILE")

        if sa_file:
            creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        elif oauth_secret:
            flow = InstalledAppFlow.from_client_secrets_file(oauth_secret, SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            raise ValueError(
                "Missing Google auth env. Set GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_OAUTH_CLIENT_SECRET_FILE."
            )

        docs_service = build("docs", "v1", credentials=creds)
        drive_service = build("drive", "v3", credentials=creds)
        return GoogleDocsClient(docs_service, drive_service)

    def get_document(self, doc_id: str) -> Dict[str, Any]:
        return self.docs.documents().get(documentId=doc_id).execute()

    def extract_paragraphs(self, doc: Dict[str, Any]) -> Tuple[str, List[Paragraph]]:
        """
        Extract plain text + paragraph list from a Docs document.
        Keeps paragraph order stable for chunking and quoting.
        """
        body = doc.get("body", {})
        content = body.get("content", [])

        paragraphs: List[Paragraph] = []
        full_text_parts: List[str] = []

        para_idx = 0
        for block in content:
            p = block.get("paragraph")
            if not p:
                continue

            elements = p.get("elements", [])
            text_runs = []
            for el in elements:
                tr = el.get("textRun")
                if tr and "content" in tr:
                    text_runs.append(tr["content"])

            text = "".join(text_runs).strip()
            if text:
                # normalize whitespace a bit
                text = re.sub(r"\s+", " ", text).strip()
                paragraphs.append(Paragraph(paragraph_index=para_idx, text=text))
                full_text_parts.append(text)
                para_idx += 1

        full_text = "\n\n".join(full_text_parts)
        return full_text, paragraphs

    def _get_document_end_index(self, doc: Dict[str, Any]) -> int:
        """
        Docs API uses a linear index. The document endIndex is typically available in the last structural element.
        """
        body = doc.get("body", {})
        content = body.get("content", [])
        if not content:
            return 1

        # Find the max endIndex in the body content
        max_end = 1
        for el in content:
            if "endIndex" in el:
                max_end = max(max_end, int(el["endIndex"]))
        return max_end

    def append_review_notes_section(self, doc_id: str, heading: str, body_markdown: str) -> None:
        """
        Appends a heading + body text at the end of the Google Doc.
        Note: This uses plain text insertion; markdown is inserted as text (simple + reliable).
        """
        doc = self.get_document(doc_id)
        end_index = self._get_document_end_index(doc)

        text_to_insert = f"\n\n{heading}\n{body_markdown}\n"
        requests = [
            {
                "insertText": {
                    "location": {"index": end_index - 1},
                    "text": text_to_insert,
                }
            },
            # Make the heading line a "HEADING_2"
            {
                "updateParagraphStyle": {
                    "range": {
                        "startIndex": end_index - 1,
                        "endIndex": end_index - 1 + len(heading) + 1,  # + newline
                    },
                    "paragraphStyle": {"namedStyleType": "HEADING_2"},
                    "fields": "namedStyleType",
                }
            },
        ]

        self.docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

    def build_linear_text_and_index_map(self, doc: dict) -> tuple[str, list[int]]:
        """
        Builds a linear string of the doc (text runs concatenated),
        and an index_map mapping each character position in the linear string
        to the corresponding Google Docs index.
        """
        body = doc.get("body", {})
        content = body.get("content", [])

        linear_chars = []
        index_map = []

        for block in content:
            p = block.get("paragraph")
            if not p:
                continue

            elements = p.get("elements", [])
            for el in elements:
                tr = el.get("textRun")
                if not tr:
                    continue
                text = tr.get("content", "")
                start = el.get("startIndex")
                end = el.get("endIndex")

                if start is None or end is None:
                    continue

                # The element covers indices [start, end)
                # text length should roughly match (end-start), but can differ in some cases.
                # We'll map char-by-char up to min lengths.
                max_len = min(len(text), end - start)

                for k in range(max_len):
                    linear_chars.append(text[k])
                    index_map.append(start + k)

        return "".join(linear_chars), index_map

    def create_named_range(self, doc_id: str, name: str, start_index: int, end_index: int) -> None:
        requests = [
            {
                "createNamedRange": {
                    "name": name,
                    "range": {
                        "startIndex": start_index,
                        "endIndex": end_index,
                    },
                }
            }
        ]
        self.docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    
    def get_named_range_id(self, doc: dict, name: str) -> str | None:
        named_ranges = doc.get("namedRanges", {})
        # namedRanges is a dict of {namedRangeId: {name, ranges...}}
        for nr_id, nr_obj in named_ranges.items():
            if nr_obj.get("name") == name:
                return nr_id
        return None

