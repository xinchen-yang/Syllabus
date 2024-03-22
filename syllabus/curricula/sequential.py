import re
import warnings
from typing import Any, Callable, List, Union

from syllabus.core import Curriculum
from syllabus.curricula import NoopCurriculum, DomainRandomization
from syllabus.task_space import TaskSpace


class SequentialCurriculum(Curriculum):
    REQUIRES_STEP_UPDATES = False
    REQUIRES_EPISODE_UPDATES = False
    REQUIRES_CENTRAL_UPDATES = False

    def __init__(self, task_list: List[Any], *curriculum_args, num_repeats: List[int] = None, repeat_list=True, **curriculum_kwargs):
        super().__init__(*curriculum_args, **curriculum_kwargs)
        self.task_list = task_list
        self.num_repeats = num_repeats if num_repeats is not None else [1] * len(task_list)
        self.repeat_list = repeat_list
        self._task_index = 0
        self._repeat_index = 0

    def _sample_distribution(self) -> List[float]:
        """
        Return None to indicate that tasks are not drawn from a distribution.
        """
        return None

    def sample(self, k: int = 1) -> Union[List, Any]:
        """
        Choose the next k tasks from the list.
        """
        tasks = []
        for _ in range(k):
            # Check if there are any tasks left to sample from
            if self._task_index >= len(self.task_list):
                self._task_index = 0
                if not self.repeat_list:
                    raise ValueError(f"Ran out of tasks to sample from. {sum(self.num_repeats)} sampled")

            # Sample the next task and increment index
            tasks.append(self.task_list[self._task_index])
            self._repeat_index += 1

            # Check if we need to repeat the current task
            if self._repeat_index >= self.num_repeats[self._task_index]:
                self._task_index += 1
                self._repeat_index = 0
        return tasks

    def remaining_tasks(self):
        """
        Return the number of tasks remaining in the manual curriculum.
        """
        if self._task_index >= len(self.task_list):
            return 0
        return (self.num_repeats[self._task_index] - self._repeat_index) + sum(repeat for repeat in self.num_repeats[self._task_index + 1:])


class SequentialMetaCurriculum(Curriculum):
    REQUIRES_STEP_UPDATES = False
    REQUIRES_EPISODE_UPDATES = True
    REQUIRES_CENTRAL_UPDATES = False

    def __init__(self, curriculum_list: List[Curriculum], stopping_conditions: List[Any], *curriculum_args, **curriculum_kwargs):
        super().__init__(*curriculum_args, **curriculum_kwargs)
        assert len(curriculum_list) > 0, "Must provide at least one curriculum"
        assert len(stopping_conditions) == len(curriculum_list) - 1, "Stopping conditions must be one less than the number of curricula. Final curriculum is used for the remainder of training"
        if len(curriculum_list) == 1:
            warnings.warn("Your sequential curriculum only containes one element. Consider using that element directly instead.")

        self.curriculum_list = self._parse_curriculum_list(curriculum_list)
        self.stopping_conditions = self._parse_stopping_conditions(stopping_conditions)
        self._curriculum_index = 0

        # Stopping metrics
        self.n_steps = 0
        self.total_steps = 0
        self.n_episodes = 0
        self.total_episodes = 0
        self.episode_returns = []

    def _parse_curriculum_list(self, curriculum_list: List[Curriculum]) -> List[Curriculum]:
        """ Parse the curriculum list to ensure that all items are curricula. 
        Adds Curriculum objects directly. Wraps task space items in NoopCurriculum objects.
        """
        parsed_list = []
        for item in curriculum_list:
            if isinstance(item, Curriculum):
                parsed_list.append(item)
            elif isinstance(item, TaskSpace):
                parsed_list.append(DomainRandomization(item))
            elif self.task_space.contains(item):
                parsed_list.append(NoopCurriculum(item, self.task_space))
            else:
                raise ValueError(f"Invalid curriculum item: {item}")

        return parsed_list

    def _parse_stopping_conditions(self, stopping_conditions: List[Any]) -> List[Any]:
        """ Parse the stopping conditions to ensure that all items are integers. """
        parsed_list = []
        for item in stopping_conditions:
            if isinstance(item, Callable):
                parsed_list.append(item)
            elif isinstance(item, str):
                parsed_list.append(self._parse_condition_string(item))
            else:
                raise ValueError(f"Invalid stopping condition: {item}")

        return parsed_list

    def _parse_condition_string(self, condition: str) -> Callable:
        """ Parse a string condition to a callable function. """

        # Parse composite conditions
        if '|' in condition:
            conditions = re.split(re.escape('|'), condition)
            return lambda: any(self._parse_condition_string(cond)() for cond in conditions)
        elif '&' in condition:
            conditions = re.split(re.escape('&'), condition)
            return lambda: all(self._parse_condition_string(cond)() for cond in conditions)

        clauses = re.split('(<=|>=|=|<|>)', condition)

        try:
            metric, comparator, value = clauses

            if metric == "steps":
                metric_fn = self._get_steps
            elif metric == "episodes":
                metric_fn = self._get_episodes
            elif metric == "episode_return":
                metric_fn = self._get_episode_return
            else:
                raise ValueError(f"Invalid metric name: {metric}")

            if comparator == '<':
                return lambda: metric_fn() < float(value)
            elif comparator == '>':
                return lambda: metric_fn() > float(value)
            elif comparator == '<=':
                return lambda: metric_fn() <= float(value)
            elif comparator == '>=':
                return lambda: metric_fn() >= float(value)
            elif comparator == '=':
                return lambda: metric_fn() == float(value)
            else:
                raise ValueError(f"Invalid comparator: {comparator}")
        except ValueError as e:
            raise ValueError(f"Invalid condition string: {condition}") from e

    def _get_steps(self):
        return self.n_steps

    def _get_total_steps(self):
        return self.total_steps

    def _get_episodes(self):
        return self.n_episodes

    def _get_total_episodes(self):
        return self.total_episodes

    def _get_episode_return(self):
        return sum(self.episode_returns) / len(self.episode_returns) if len(self.episode_returns) > 0 else 0

    @property
    def current_curriculum(self):
        return self.curriculum_list[self._curriculum_index]

    def _sample_distribution(self) -> List[float]:
        """
        Return None to indicate that tasks are not drawn from a distribution.
        """
        return None

    def sample(self, k: int = 1) -> Union[List, Any]:
        """
        Choose the next k tasks from the list.
        """
        curriculum = self.current_curriculum
        tasks = curriculum.sample(k)

        # Recode tasks into environment task space
        decoded_tasks = [curriculum.task_space.decode(task) for task in tasks]
        recoded_tasks = [self.task_space.encode(task) for task in decoded_tasks]
        return recoded_tasks

    def update_on_episode(self, episode_return, episode_len, episode_task, env_id: int = None):
        self.n_episodes += 1
        self.total_episodes += 1
        self.n_steps += episode_len
        self.total_steps += episode_len
        self.episode_returns.append(episode_return)
        # Check if we should move on to the next phase of the curriculum
        if self._curriculum_index < len(self.stopping_conditions) and self.stopping_conditions[self._curriculum_index]():
            self._curriculum_index += 1
            self.n_episodes = 0
            self.n_steps = 0
            self.episode_returns = []
