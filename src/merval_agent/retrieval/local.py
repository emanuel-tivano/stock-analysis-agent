from typing import Literal, Protocol

from merval_agent.domain.models import Evidence


class MethodologyRetriever(Protocol):
    def search(self, query: str, source: Literal["murphy", "graham"]) -> list[Evidence]: ...


class LocalMethodologyRetriever:
    """Original teaching notes, not quotations or retrieval from the private books."""

    def search(self, query: str, source: Literal["murphy", "graham"]) -> list[Evidence]:
        notes = {
            "murphy": "Contrastar tendencia, momentum y volumen; un indicador aislado no valida una conclusión.",
            "graham": "Examinar calidad de evidencia y solidez financiera antes de interpretar una valoración.",
        }
        return [
            Evidence(
                source=f"local-demo:{source}",
                chunk_id=f"{source}-demo-1",
                text=notes[source],
                score=0.0,
                kind="DEMO",
                metadata={
                    "author": "project teaching note",
                    "query": query,
                    "book_retrieval": False,
                },
            )
        ]
