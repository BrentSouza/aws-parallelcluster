#  Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
#
#  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
#  with the License. A copy of the License is located at http://aws.amazon.com/apache2.0/
#  or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
#  limitations under the License.
import base64
import functools
import logging
import os
from typing import List, Optional, Set

from flask import request
from pkg_resources import packaging

from pcluster.api.errors import (
    BadRequestException,
    ConflictException,
    InternalServiceException,
    LimitExceededException,
    ParallelClusterApiException,
)
from pcluster.config.common import AllValidatorsSuppressor, TypeMatchValidatorsSuppressor, ValidatorSuppressor
from pcluster.constants import SUPPORTED_REGIONS
from pcluster.exceptions import BadRequest, Conflict, LimitExceeded

LOGGER = logging.getLogger(__name__)


def configure_aws_region(is_query_string_arg: bool = True):
    """
    Handle region validation and configuration for API controllers.

    When a controller is decorated with @configure_aws_region, the region value passed either as a query stirng
    argument or as a body parameter is validated and then set in the environment so that all AWS clients make use
    of it.

    :param is_query_string_arg: set to False when the region configuration is in the request body
    """

    def _decorator_validate_region(func):
        @functools.wraps(func)
        def _wrapper_validate_region(*args, **kwargs):
            region = kwargs.get("region") if is_query_string_arg else request.get_json().get("region")
            if not region:
                region = os.environ.get("AWS_DEFAULT_REGION")

            if not region:
                raise BadRequestException("region needs to be set")
            if region not in SUPPORTED_REGIONS:
                raise BadRequestException(f"invalid or unsupported region '{region}'")

            LOGGER.info("Setting AWS Region to %s", region)
            os.environ["AWS_DEFAULT_REGION"] = region

            return func(*args, **kwargs)

        return _wrapper_validate_region

    return _decorator_validate_region


def check_cluster_version(cluster):
    return cluster.stack.version and packaging.version.parse("4.0.0") > packaging.version.parse(
        cluster.stack.version
    ) >= packaging.version.parse("3.0.0")


def read_config(base64_encoded_config: str) -> str:
    try:
        config = base64.b64decode(base64_encoded_config).decode("UTF-8")
    except Exception as e:
        LOGGER.error("Failed when decoding configuration: %s", e)
        raise BadRequestException("invalid configuration. Please make sure the string is base64 encoded.")

    if not config:
        LOGGER.error("Failed: configuration is required and cannot be empty")
        raise BadRequestException("configuration is required and cannot be empty")

    return config


def convert_errors():
    def _decorate_api(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ParallelClusterApiException as e:
                error = e
            except LimitExceeded as e:
                error = LimitExceededException(str(e))
            except BadRequest as e:
                error = BadRequestException(str(e))
            except Conflict as e:
                error = ConflictException(str(e))
            except Exception as e:
                error = InternalServiceException(str(e))
            raise error

        return wrapper

    return _decorate_api


def get_validator_suppressors(suppress_validators: Optional[List[str]]) -> Set[ValidatorSuppressor]:
    validator_suppressors: Set[ValidatorSuppressor] = set()
    if not suppress_validators:
        return validator_suppressors

    validator_types_to_suppress = set()
    for suppress_validator_expression in suppress_validators:
        if suppress_validator_expression == "ALL":
            validator_suppressors.add(AllValidatorsSuppressor())
        elif suppress_validator_expression.startswith("type:"):
            validator_types_to_suppress.add(suppress_validator_expression[len("type:") :])  # noqa: E203

    if validator_types_to_suppress:
        validator_suppressors.add(TypeMatchValidatorsSuppressor(validator_types_to_suppress))

    return validator_suppressors
