""" Test curriculum synchronization across multiple processes. """
import time
import random
from multiprocessing import SimpleQueue, Process
from copy import deepcopy

import ray

from nle.env.tasks import NetHackScore
from syllabus.examples import NethackTaskWrapper
from syllabus.curricula import NoopCurriculum, UniformCurriculum, LearningProgressCurriculum, PrioritizedLevelReplay
from syllabus.core import (MultiProcessingSyncWrapper,
                           RaySyncWrapper,
                           MultiProcessingCurriculumWrapper,
                           make_multiprocessing_curriculum,
                           make_ray_curriculum)
from syllabus.tests import test_single_process, test_native_multiprocess, test_ray_multiprocess, create_nethack_env

N_ENVS = 128
N_EPISODES = 16

if __name__ == "__main__":
    ray.init()
    sample_env = create_nethack_env()
    curricula = [
        (NoopCurriculum, (NetHackScore, sample_env.task_space), {}),
        (UniformCurriculum, (sample_env.task_space,), {}),
        (LearningProgressCurriculum, (sample_env.task_space,), {}),
        (PrioritizedLevelReplay, (sample_env.task_space,), {"device":"cpu", "suppress_usage_warnings":True, "num_processes":N_ENVS}),
    ]
    for curriculum, args, kwargs in curricula:
        print("")
        print("*" * 80)
        print("Testing curriculum:", curriculum.__name__)
        print("*" * 80)
        print("")

        # Test single process speed
        print("RUNNING: Python single process test (4 envs)...")
        test_curriculum = curriculum(*args, **kwargs)
        native_speed = test_single_process(create_nethack_env, curriculum=test_curriculum, num_envs=4, num_episodes=N_EPISODES)
        print(f"PASSED: single process test (4 envs) passed: {native_speed:.2f}s")

        # Test Queue multiprocess speed with Syllabus
        test_curriculum = curriculum(*args, **kwargs)
        test_curriculum, task_queue, update_queue = make_multiprocessing_curriculum(test_curriculum)
        print("\nRUNNING: Python multiprocess test with Syllabus...")
        native_syllabus_speed = test_native_multiprocess(create_nethack_env, curriculum=test_curriculum, num_envs=N_ENVS, num_episodes=N_EPISODES)
        print(f"PASSED: Python multiprocess test with Syllabus: {native_syllabus_speed:.2f}s")

        # Test Ray multiprocess speed with Syllabus
        test_curriculum = curriculum(*args, **kwargs)
        test_curriculum = make_ray_curriculum(test_curriculum)
        print("\nRUNNING: Ray multiprocess test with Syllabus...")
        ray_syllabus_speed = test_ray_multiprocess(create_nethack_env, num_envs=N_ENVS, num_episodes=N_EPISODES)
        print(f"PASSED: Ray multiprocess test with Syllabus: {ray_syllabus_speed:.2f}s")