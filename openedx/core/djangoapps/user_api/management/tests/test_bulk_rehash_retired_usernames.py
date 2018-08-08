"""
Test the bulk_rehash_retired_usernames management command
"""
import pytest

from django.core.management import call_command

from openedx.core.djangoapps.user_api.accounts.tests.retirement_helpers import RetirementTestCase, fake_retirement
from openedx.core.djangoapps.user_api.models import UserRetirementStatus
from openedx.core.djangolib.testing.utils import skip_unless_lms
from student.models import get_retired_username_by_username
from student.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _setup_users():
    """
    Creates and returns test users in the different states of needing rehash:
    - Skipped: has not yet been retired
    - Faked: has been fake-retired, but the retired username does not require updating
    - Needing rehash: has been fake-retired and name changed so it triggers a hash update
    """
    # When we loop through creating users, take additional action on these
    user_indexes_to_be_fake_retired = (2, 4, 6, 8, 10)
    user_indexes_to_be_rehashed = (4, 6)

    users_skipped = []
    users_faked = []
    users_needing_rehash = []
    retirements = {}

    # Create some test users with retirements
    for i in range(1, 11):
        user = UserFactory()
        retirement = UserRetirementStatus.create_retirement(user)
        retirements[user.id] = retirement

        if i in user_indexes_to_be_fake_retired:
            fake_retirement(user)

            if i in user_indexes_to_be_rehashed:
                # In order to need a rehash user.username must be the same as
                # retirement.retired_username and NOT the same as the hash
                # generated when the script is run. So we force that here.
                retirement.retired_username = retirement.retired_username.upper()
                user.username = retirement.retired_username
                retirement.save()
                user.save()
                users_needing_rehash.append(user)
            else:
                users_faked.append(user)
        else:
            users_skipped.append(user)
    return users_skipped, users_faked, users_needing_rehash, retirements


@skip_unless_lms
def test_successful_rehash(capsys):
    """
    Run the command with users of all different hash statuses, expect success
    """
    RetirementTestCase.setup_states()
    users_skipped, users_faked, users_needing_rehash, retirements = _setup_users()
    call_command('bulk_rehash_retired_usernames')
    output = capsys.readouterr().out

    for user in users_skipped:
        assert "User ID {} because the user does not appear to have a retired username:".format(user.id) in output

    for user in users_faked:
        assert "User ID {} because the hash would not change.".format(user.id) in output

    for user in users_needing_rehash:
        retirement = retirements[user.id]
        user.refresh_from_db()
        retirement.refresh_from_db()
        new_retired_username = get_retired_username_by_username(retirement.original_username)

        assert "User ID {} to rehash their retired username".format(user.id) in output
        assert new_retired_username == user.username
        assert new_retired_username == retirement.retired_username
