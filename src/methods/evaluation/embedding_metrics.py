
import torch
import torch.nn.functional as F


@torch.no_grad()
def evaluate_embeddings(
    predictions,
    targets,
    query_ids,
    gallery_embeddings=None,
    gallery_ids=None,
):
    """
    predictions: [N, D]
    targets: [N, D]
    query_ids: list[str], length N

    gallery_embeddings: [G, D], optional
    gallery_ids: list[str], length G, optional

    Returns per-query metrics so they can be
    aggregated by game and actor_seen.
    """
    predictions = F.normalize(
        predictions.float(), dim=-1
    )
    targets = F.normalize(
        targets.float(), dim=-1
    )

    if gallery_embeddings is None:
        gallery_embeddings = targets
        gallery_ids = query_ids
    else:
        gallery_embeddings = F.normalize(
            gallery_embeddings.float(), dim=-1
        )

    if len(set(gallery_ids)) != len(gallery_ids):
        raise ValueError("Duplicate gallery character IDs")

    if len(set(query_ids)) != len(query_ids):
        raise ValueError("Duplicate query character IDs")

    gallery_lookup = {
        char_id: i
        for i, char_id in enumerate(gallery_ids)
    }

    if any(c not in gallery_lookup for c in query_ids):
        raise ValueError(
            "Some query characters are missing from gallery"
        )

    # Cosine with the correct target
    cosine_per_query = F.cosine_similarity(
        predictions, targets, dim=-1
    )

    # Retrieval against fixed gallery
    scores = predictions @ gallery_embeddings.T

    correct_indices = torch.tensor(
        [gallery_lookup[c] for c in query_ids],
        device=scores.device,
        dtype=torch.long,
    )

    # Rank = 1 + number of candidates scored higher.
    # argsort handles ties by its ordering.
    rankings = scores.argsort(
        dim=1, descending=True
    )

    ranks = (
        rankings == correct_indices[:, None]
    ).int().argmax(dim=1) + 1

    return {
        "cosine": cosine_per_query,
        "r1": (ranks <= 1).float(),
        "r5": (ranks <= 5).float(),
        "mrr": 1.0 / ranks.float(),
        "rank": ranks,
    }


def aggregate_metrics(metrics, indices=None):
    if indices is None:
        indices = torch.arange(
            len(metrics["cosine"]),
            device=metrics["cosine"].device,
        )

    if len(indices) == 0:
        return None

    return {
        "count": len(indices),
        "cosine": metrics["cosine"][indices].mean().item(),
        "r1": metrics["r1"][indices].mean().item(),
        "r5": metrics["r5"][indices].mean().item(),
        "mrr": metrics["mrr"][indices].mean().item(),
    }
