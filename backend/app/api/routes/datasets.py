from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_dataset_service, get_db
from app.services.dataset_service import DatasetService, dataset_to_dict

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])


@router.post("", status_code=201)
def upload_dataset(file: UploadFile, db: Session = Depends(get_db), service: DatasetService = Depends(get_dataset_service)):
    dataset = service.upload(db, file.filename or "upload", file.file)
    return dataset_to_dict(dataset)


@router.get("")
def list_datasets(db: Session = Depends(get_db), service: DatasetService = Depends(get_dataset_service)):
    return [dataset_to_dict(d) for d in service.list(db)]


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str, db: Session = Depends(get_db), service: DatasetService = Depends(get_dataset_service)):
    return dataset_to_dict(service.get(db, dataset_id))


@router.get("/{dataset_id}/profile")
def get_profile(dataset_id: str, db: Session = Depends(get_db), service: DatasetService = Depends(get_dataset_service)):
    return service.get(db, dataset_id).profile.profile


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str, db: Session = Depends(get_db), service: DatasetService = Depends(get_dataset_service)):
    service.delete(db, dataset_id)
