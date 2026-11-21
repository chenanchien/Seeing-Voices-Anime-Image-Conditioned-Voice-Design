
import torch
from src.methods.evaluation.embedding_metrics import (
    evaluate_embeddings,
    aggregate_metrics,
)


def train_one_epoch(
    model,
    loader,
    optimizer,
    info_criterion,
    cosine_criterion,
    device,
    lambda_cosine=1.0,
):
    model.train()

    total_loss = 0.0
    total_info = 0.0
    total_cosine = 0.0
    total_samples = 0

    for batch in loader:
        images = batch["image_embedding"].to(device)
        targets = batch["voice_prototype"].to(device)
        actor_ids = batch["actor_id"]

        optimizer.zero_grad(set_to_none=True)

        predictions = model(images)

        loss_info = info_criterion(
            predictions,
            targets,
            actor_ids,
        )

        loss_cosine = cosine_criterion(
            predictions,
            targets,
        )

        loss = loss_info + lambda_cosine * loss_cosine

        loss.backward()
        optimizer.step()

        batch_size = images.size(0)

        total_samples += batch_size
        total_loss += loss.item() * batch_size
        total_info += loss_info.item() * batch_size
        total_cosine += loss_cosine.item() * batch_size

    return {
        "loss": total_loss / total_samples,
        "infonce": total_info / total_samples,
        "cosine": total_cosine / total_samples,
    }


@torch.no_grad()
def validate(model, loader, device):
    model.eval()

    total_similarity = 0.0
    total_samples = 0

def validate(model, loader, device):
    model.eval()

    all_predictions = []
    all_targets = []
    all_character_ids = []

    for batch in loader:
        images = batch["image_embedding"].to(device)
        targets = batch["voice_prototype"].to(device)

        predictions = model(images)

        all_predictions.append(predictions)
        all_targets.append(targets)
        all_character_ids.extend(batch["character_id"])

    predictions = torch.cat(all_predictions, dim=0)
    targets = torch.cat(all_targets, dim=0)

    metrics = evaluate_embeddings(
        predictions=predictions,
        targets=targets,
        query_ids=all_character_ids,
    )
    return aggregate_metrics(metrics)