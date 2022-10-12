import random

import cv2
from keras.callbacks import ModelCheckpoint, TensorBoard
from LSC_recognizer_model.src.coordenates.data.split_dataset import SplitDataset
from LSC_recognizer_model.src.coordenates.models.callbacks import SaveResultsOnDatabaseCallback
from LSC_recognizer_model.src.coordenates.models.coordenates_models import (
    INPUT_SHAPE_FIX,
    get_model_coord_dense_3,
)
from LSC_recognizer_model.src.utils.sign_model import SignModel
from repositories.callback_repository import CallbackRepository, CallbackRepositoryTinyDB
from settings import PATH_CHECKPOINTS_SAVE, PATH_RAW_NUMPY, PATH_RAW_SIGNS


class ModelController:
    def __init__(self, callback_repository: CallbackRepository):
        self.callback_repository = callback_repository

    def get_training_info(self, id_training: int):
        return self.callback_repository.get_training_info(id_training)

    def generate_dataset(self):
        def single_aug(image):
            image = cv2.flip(image, 1)
            return image

        def rotation(image, angle):
            angle = int(random.uniform(-angle, angle))
            h, w = image.shape[:2]
            M = cv2.getRotationMatrix2D((int(w / 2), int(h / 2)), angle, 1)
            image = cv2.warpAffine(image, M, (w, h))
            return image

        def zoom(img, value):
            def fill(img, h, w):
                img = cv2.resize(img, (h, w), cv2.INTER_CUBIC)
                return img

            if value > 1 or value < 0:
                print("Value for zoom should be less than 1 and greater than 0")
                return img

            value = random.uniform(value, 1)
            h, w = img.shape[:2]
            h_taken = int(value * h)
            w_taken = int(value * w)
            h_start = random.randint(0, h - h_taken)
            w_start = random.randint(0, w - w_taken)
            img = img[h_start : h_start + h_taken, w_start : w_start + w_taken, :]
            img = fill(img, h, w)
            return img

        image_single_aug = (1, single_aug)
        image_separated_aug = [
            (3, lambda image: rotation(image, 10)),
            (3, lambda image: zoom(image, 0.5)),
        ]

        split_dataset = SplitDataset(path_raw_image=PATH_RAW_SIGNS)
        train, test, validation = split_dataset.get_splited_files(
            save_path_numpy=PATH_RAW_NUMPY,
            # save_path_image_detection_draw = PATH_PREDICTED_IMG,
            image_single_aug=image_single_aug,
            image_separated_aug=image_separated_aug,
            cant_rotations_per_axie_data_aug=[2, 2, 2],
            x_max_rotation=25,
            y_max_rotation=40,
            z_max_rotation=20,
        )

    async def train_model(self):
        # -----------------------------------------------
        # Split Dataset Layer (Train, Test, Validation)
        # -----------------------------------------------

        split_dataset = SplitDataset(path_raw_numpy=PATH_RAW_NUMPY)
        train, test, validation = split_dataset.get_splited_files()

        # FIX data
        X_train, Y_train = split_dataset.get_only_specific_parts_and_fix(
            train, used_parts=["pose", "left_hand", "right_hand"]
        )
        X_test, Y_test = split_dataset.get_only_specific_parts_and_fix(
            test, used_parts=["pose", "left_hand", "right_hand"]
        )
        X_validation, Y_validation = split_dataset.get_only_specific_parts_and_fix(
            validation, used_parts=["pose", "left_hand", "right_hand"]
        )

        # -----------------------------------------------
        # Model Layer
        # -----------------------------------------------

        # 1. Create Model layer and define hyperparameters
        classes = split_dataset.get_classes()
        steps_per_epoch = split_dataset.get_recomend_steps_per_epoch()
        epochs = 600

        modelo = SignModel(
            model=get_model_coord_dense_3(INPUT_SHAPE_FIX, len(classes)),
            dataset_train=None,
            dataset_validation=None,
            X_train=X_train,
            Y_train=Y_train,
            X_validation=X_validation,
            Y_validation=Y_validation,
        )

        # 2. Define callbacks

        # ============ TensorBoard ============
        # To open tensorboard: tensorboard --logdir=. on the folder where the logs are.
        log_dir = f"{PATH_CHECKPOINTS_SAVE}/logs"
        tb_callback = TensorBoard(log_dir=log_dir)

        # ============ Checkpoints ============
        checkpoint_filepath = PATH_CHECKPOINTS_SAVE
        checkpoint = ModelCheckpoint(
            filepath=checkpoint_filepath, monitor="val_accuracy", verbose=1, save_best_only=True, mode="max"
        )

        # ========== Callbacks list ============
        callbacks_list = [
            checkpoint,
            tb_callback,
            SaveResultsOnDatabaseCallback(CallbackRepositoryTinyDB(), epochs),
        ]

        # 3. Train model

        modelo.train_model(
            epochs=epochs,
            optimizer="Adam",
            loss="categorical_crossentropy",
            metrics=["accuracy"],
            callbacks=callbacks_list,
            steps_per_epoch=steps_per_epoch,
            verbose=1,
        )

        # 4. Save plots of the training
        plot_acc_los, plot_confusion_matrix = modelo.save_plot_results(
            X_test=X_test, Y_test=Y_test, path_to_save=PATH_CHECKPOINTS_SAVE
        )
