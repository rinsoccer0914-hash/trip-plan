import json
import uuid
from datetime import date

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .models import (
    CardResponse, CardTemplate, Group, PlanLike, Profile, ScheduleItem, TravelPlan,
)
from .views import CARD_TYPE_ORDER, DEFAULT_CARDS, _build_days_data, ensure_defaults


class RegistrationLoginTests(TestCase):
    def test_register_creates_user_and_profile_then_redirects_to_top(self):
        resp = self.client.post(reverse('register'), {
            'username': 'alice', 'password': 'pass1234', 'home_address': '東京都渋谷区渋谷',
        })
        self.assertTrue(User.objects.filter(username='alice').exists())
        self.assertRedirects(resp, reverse('top'))
        self.assertEqual(User.objects.get(username='alice').profile.home_address, '東京都渋谷区渋谷')

    def test_register_without_address_still_redirects_to_top(self):
        resp = self.client.post(reverse('register'), {'username': 'erin', 'password': 'pass1234'})
        self.assertRedirects(resp, reverse('top'))
        self.assertEqual(User.objects.get(username='erin').profile.home_address, '')

    def test_register_duplicate_username_shows_error_and_does_not_create_second_user(self):
        User.objects.create_user(username='bob', password='pass1234')
        resp = self.client.post(reverse('register'), {'username': 'bob', 'password': 'pass1234'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'そのユーザー名はすでに使われています')
        self.assertEqual(User.objects.filter(username='bob').count(), 1)

    def test_register_username_surrounding_whitespace_still_detected_as_duplicate(self):
        User.objects.create_user(username='carol', password='pass1234')
        resp = self.client.post(reverse('register'), {'username': '  carol  ', 'password': 'pass1234'})
        self.assertContains(resp, 'そのユーザー名はすでに使われています')
        self.assertEqual(User.objects.filter(username='carol').count(), 1)

    def test_register_short_password_rejected(self):
        resp = self.client.post(reverse('register'), {'username': 'dave', 'password': '12'})
        self.assertContains(resp, 'パスワードは4文字以上にしてください')
        self.assertFalse(User.objects.filter(username='dave').exists())

    def test_login_success_with_address_goes_to_top(self):
        user = User.objects.create_user(username='frank', password='pass1234')
        Profile.objects.create(user=user, home_address='大阪府大阪市')
        resp = self.client.post(reverse('login'), {'username': 'frank', 'password': 'pass1234'})
        self.assertRedirects(resp, reverse('top'))

    def test_login_without_saved_address_still_goes_to_top(self):
        User.objects.create_user(username='frank2', password='pass1234')
        resp = self.client.post(reverse('login'), {'username': 'frank2', 'password': 'pass1234'})
        self.assertRedirects(resp, reverse('top'))

    def test_login_wrong_password_shows_error(self):
        User.objects.create_user(username='gina', password='pass1234')
        resp = self.client.post(reverse('login'), {'username': 'gina', 'password': 'wrong'})
        self.assertContains(resp, 'ユーザー名またはパスワードが正しくありません')

    def test_login_nonexistent_user_shows_error(self):
        resp = self.client.post(reverse('login'), {'username': 'nobody', 'password': 'x'})
        self.assertContains(resp, 'ユーザー名またはパスワードが正しくありません')

    def test_logout_then_protected_page_redirects_to_login(self):
        user = User.objects.create_user(username='hank', password='pass1234')
        Profile.objects.create(user=user, home_address='x')
        self.client.force_login(user)
        self.client.post(reverse('logout'))
        resp = self.client.get(reverse('top'))
        self.assertRedirects(resp, f"{reverse('login')}?next={reverse('top')}")


class SetHomeAddressTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ivy', password='pass1234')
        self.client.force_login(self.user)

    def test_get_shows_form(self):
        resp = self.client.get(reverse('set_home_address'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '<form method="post">')

    def test_post_saves_address_and_redirects_to_top(self):
        resp = self.client.post(reverse('set_home_address'), {'home_address': '福岡県福岡市'})
        self.assertRedirects(resp, reverse('top'))
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.home_address, '福岡県福岡市')

    def test_skip_link_goes_to_top_without_saving(self):
        resp = self.client.get(reverse('top'))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Profile.objects.filter(user=self.user).exclude(home_address='').exists())


class MyInfoPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='mypageuser', password='pass1234')
        Profile.objects.create(user=self.user, home_address='東京都新宿区')
        self.other = User.objects.create_user(username='mypageother', password='pass1234')
        self.client.force_login(self.user)

    def test_shows_username_and_address(self):
        resp = self.client.get(reverse('my_info'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'mypageuser')
        self.assertContains(resp, '東京都新宿区')

    def test_shows_only_own_plans_not_others(self):
        TravelPlan.objects.create(user=self.user, name='自分のプラン')
        TravelPlan.objects.create(user=self.other, name='他人のプラン')
        resp = self.client.get(reverse('my_info'))
        self.assertContains(resp, '自分のプラン')
        self.assertNotContains(resp, '他人のプラン')

    def test_group_shared_plan_owned_by_someone_else_not_listed(self):
        group = Group.objects.create(name='共有グループ', owner=self.other)
        group.members.add(self.user)
        plan = TravelPlan.objects.create(user=self.other, name='共有された側のプラン', group=group)
        resp = self.client.get(reverse('my_info'))
        self.assertNotContains(resp, '共有された側のプラン')

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse('my_info'))
        self.assertRedirects(resp, f"{reverse('login')}?next={reverse('my_info')}")


class PlanManagementTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner1', password='pass1234')
        Profile.objects.create(user=self.owner, home_address='x')
        self.stranger = User.objects.create_user(username='stranger1', password='pass1234')
        Profile.objects.create(user=self.stranger, home_address='x')
        self.client.force_login(self.owner)

    def test_create_plan(self):
        resp = self.client.post(reverse('plan_new'), {
            'name': '沖縄旅行', 'start_date': '2026-09-01', 'end_date': '2026-09-03',
            'participant_count': '3',
        })
        plan = TravelPlan.objects.get(name='沖縄旅行')
        self.assertRedirects(resp, reverse('plan_edit', args=[plan.pk]))
        self.assertEqual(plan.user, self.owner)
        self.assertEqual(plan.day_count, 3)
        self.assertEqual(plan.participant_count, 3)

    def test_top_view_only_lists_own_and_group_plans(self):
        TravelPlan.objects.create(user=self.owner, name='自分のプラン')
        TravelPlan.objects.create(user=self.stranger, name='他人のプラン')
        resp = self.client.get(reverse('top'))
        self.assertContains(resp, '自分のプラン')
        self.assertNotContains(resp, '他人のプラン')

    def test_unrelated_user_cannot_open_plan_edit(self):
        plan = TravelPlan.objects.create(user=self.owner, name='秘密のプラン')
        self.client.force_login(self.stranger)
        resp = self.client.get(reverse('plan_edit', args=[plan.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_group_member_can_view_but_not_edit(self):
        plan = TravelPlan.objects.create(user=self.owner, name='共有プラン')
        group = Group.objects.create(name='友人', owner=self.owner)
        group.members.add(self.stranger)
        plan.group = group
        plan.save(update_fields=['group'])

        self.client.force_login(self.stranger)
        resp = self.client.get(reverse('plan_edit', args=[plan.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['is_owner'])

    def test_rename_plan(self):
        plan = TravelPlan.objects.create(user=self.owner, name='旧名')
        self.client.post(reverse('plan_edit', args=[plan.pk]), {'name': '新名'})
        plan.refresh_from_db()
        self.assertEqual(plan.name, '新名')

    def test_owner_can_delete_plan(self):
        plan = TravelPlan.objects.create(user=self.owner, name='削除対象')
        self.client.post(reverse('plan_delete', args=[plan.pk]))
        self.assertFalse(TravelPlan.objects.filter(pk=plan.pk).exists())

    def test_non_owner_cannot_delete_plan(self):
        plan = TravelPlan.objects.create(user=self.owner, name='守られるプラン')
        self.client.force_login(self.stranger)
        resp = self.client.post(reverse('plan_delete', args=[plan.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(TravelPlan.objects.filter(pk=plan.pk).exists())

    def test_missing_plan_is_404(self):
        resp = self.client.get(reverse('plan_edit', args=[999999]))
        self.assertEqual(resp.status_code, 404)


class WarikanAndParticipantsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner2', password='pass1234')
        Profile.objects.create(user=self.owner, home_address='x')
        self.stranger = User.objects.create_user(username='stranger2', password='pass1234')
        self.plan = TravelPlan.objects.create(user=self.owner, name='割り勘テスト')
        self.client.force_login(self.owner)

    def test_toggle_warikan_flips_state(self):
        self.assertFalse(self.plan.warikan_enabled)
        self.client.post(reverse('plan_toggle_warikan', args=[self.plan.pk]))
        self.plan.refresh_from_db()
        self.assertTrue(self.plan.warikan_enabled)
        self.client.post(reverse('plan_toggle_warikan', args=[self.plan.pk]))
        self.plan.refresh_from_db()
        self.assertFalse(self.plan.warikan_enabled)

    def test_non_owner_cannot_toggle_warikan(self):
        self.client.force_login(self.stranger)
        resp = self.client.post(reverse('plan_toggle_warikan', args=[self.plan.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_set_participants_updates_count_and_splits_cost(self):
        self.client.post(reverse('plan_set_participants', args=[self.plan.pk]), {'participant_count': '4'})
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.participant_count, 4)
        item = ScheduleItem.objects.create(plan=self.plan, name='夕食', card_type='eat', cost=1000)
        self.assertEqual(item.cost_per_person, 250)

    def test_set_participants_ignores_invalid_value(self):
        self.client.post(reverse('plan_set_participants', args=[self.plan.pk]), {'participant_count': 'not-a-number'})
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.participant_count, 1)


class CardTemplateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cardowner', password='pass1234')
        Profile.objects.create(user=self.user, home_address='x')
        self.client.force_login(self.user)

    def test_ensure_defaults_creates_exactly_seven_defaults(self):
        ensure_defaults(self.user)
        names = set(CardTemplate.objects.filter(user=self.user, is_default=True).values_list('name', flat=True))
        self.assertEqual(names, {name for name, _ in DEFAULT_CARDS})

    def test_ensure_defaults_is_idempotent(self):
        ensure_defaults(self.user)
        ensure_defaults(self.user)
        self.assertEqual(CardTemplate.objects.filter(user=self.user, is_default=True).count(), len(DEFAULT_CARDS))

    def test_ensure_defaults_migrates_retired_names(self):
        CardTemplate.objects.create(user=self.user, name='朝食', card_type='eat', is_default=True)
        ensure_defaults(self.user)
        names = set(CardTemplate.objects.filter(user=self.user, is_default=True).values_list('name', flat=True))
        self.assertNotIn('朝食', names)
        self.assertIn('ご飯', names)

    def test_palette_order_matches_card_type_order(self):
        ensure_defaults(self.user)
        resp = self.client.get(reverse('card_templates'))
        templates = list(resp.context['templates'])
        seen_types = [t.card_type for t in templates if t.is_default]
        self.assertEqual(seen_types, CARD_TYPE_ORDER)

    def test_create_custom_card(self):
        self.client.post(reverse('card_templates'), {'name': '東京タワー', 'card_type': 'see'})
        self.assertTrue(CardTemplate.objects.filter(user=self.user, name='東京タワー', is_default=False).exists())

    def test_delete_own_card(self):
        tpl = CardTemplate.objects.create(user=self.user, name='自作カード', card_type='free')
        self.client.post(reverse('card_template_delete', args=[tpl.pk]))
        self.assertFalse(CardTemplate.objects.filter(pk=tpl.pk).exists())

    def test_cannot_delete_other_users_card(self):
        other = User.objects.create_user(username='otherowner', password='pass1234')
        tpl = CardTemplate.objects.create(user=other, name='他人のカード', card_type='free')
        resp = self.client.post(reverse('card_template_delete', args=[tpl.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(CardTemplate.objects.filter(pk=tpl.pk).exists())


class ScheduleItemApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='scheduleowner', password='pass1234')
        Profile.objects.create(user=self.owner, home_address='x')
        self.stranger = User.objects.create_user(username='schedulestranger', password='pass1234')
        self.plan = TravelPlan.objects.create(
            user=self.owner, name='スケジュールテスト',
            start_date=date(2026, 8, 1), end_date=date(2026, 8, 2),
        )
        self.move_tpl = CardTemplate.objects.create(user=self.owner, name='移動', card_type='move')
        self.wake_tpl = CardTemplate.objects.create(user=self.owner, name='起床・就寝', card_type='wake')
        self.client.force_login(self.owner)

    def _post_json(self, url, payload):
        return self.client.post(url, data=json.dumps(payload), content_type='application/json')

    def test_add_item_snaps_time_and_duration_to_15_minutes(self):
        resp = self._post_json(reverse('api_add_item', args=[self.plan.pk]), {
            'day': 1, 'template_id': self.move_tpl.pk, 'start_time': '09:07', 'duration_minutes': 40,
        })
        body = resp.json()
        self.assertEqual(body['start_time'], '09:00')
        self.assertEqual(body['duration_minutes'], 45)

    def test_add_move_item_stores_from_to_location(self):
        resp = self._post_json(reverse('api_add_item', args=[self.plan.pk]), {
            'day': 1, 'template_id': self.move_tpl.pk, 'start_time': '10:00',
            'from_location': '東京駅', 'to_location': '横浜駅',
        })
        body = resp.json()
        self.assertEqual(body['from_location'], '東京駅')
        self.assertEqual(body['to_location'], '横浜駅')

    def test_non_move_item_ignores_from_to_location(self):
        see_tpl = CardTemplate.objects.create(user=self.owner, name='観光', card_type='see')
        resp = self._post_json(reverse('api_add_item', args=[self.plan.pk]), {
            'day': 1, 'template_id': see_tpl.pk, 'from_location': '東京駅', 'to_location': '横浜駅',
        })
        body = resp.json()
        self.assertEqual(body['from_location'], '')
        self.assertEqual(body['to_location'], '')

    def test_valid_subtype_overrides_item_name(self):
        resp = self._post_json(reverse('api_add_item', args=[self.plan.pk]), {
            'day': 1, 'template_id': self.move_tpl.pk, 'subtype': '電車',
        })
        self.assertEqual(resp.json()['name'], '電車')

    def test_invalid_subtype_falls_back_to_template_name(self):
        resp = self._post_json(reverse('api_add_item', args=[self.plan.pk]), {
            'day': 1, 'template_id': self.move_tpl.pk, 'subtype': 'でっちあげ',
        })
        self.assertEqual(resp.json()['name'], '移動')

    def test_alarm_only_stored_for_wake_cards(self):
        resp = self._post_json(reverse('api_add_item', args=[self.plan.pk]), {
            'day': 1, 'template_id': self.wake_tpl.pk, 'alarm_enabled': True,
        })
        self.assertTrue(resp.json()['alarm_enabled'])

        resp2 = self._post_json(reverse('api_add_item', args=[self.plan.pk]), {
            'day': 1, 'template_id': self.move_tpl.pk, 'alarm_enabled': True,
        })
        self.assertFalse(resp2.json()['alarm_enabled'])

    def test_non_owner_cannot_add_item(self):
        self.client.force_login(self.stranger)
        resp = self._post_json(reverse('api_add_item', args=[self.plan.pk]), {
            'day': 1, 'template_id': self.move_tpl.pk,
        })
        self.assertEqual(resp.status_code, 404)

    def test_update_time_changes_day_and_resets_order(self):
        item = ScheduleItem.objects.create(plan=self.plan, name='移動', card_type='move', day_number=1, order=0)
        ScheduleItem.objects.create(plan=self.plan, name='既存', card_type='free', day_number=2, order=0)
        resp = self._post_json(
            reverse('api_update_time', args=[self.plan.pk, item.pk]), {'day': 2, 'start_time': '13:00'},
        )
        body = resp.json()
        self.assertEqual(body['day'], 2)
        item.refresh_from_db()
        self.assertEqual(item.day_number, 2)
        self.assertEqual(item.order, 1)

    def test_update_cost_and_cost_per_person(self):
        self.plan.participant_count = 2
        self.plan.save(update_fields=['participant_count'])
        item = ScheduleItem.objects.create(plan=self.plan, name='夕食', card_type='eat')
        resp = self._post_json(reverse('api_update_time', args=[self.plan.pk, item.pk]), {'cost': 3000})
        body = resp.json()
        self.assertEqual(body['cost'], 3000)
        self.assertEqual(body['cost_per_person'], 1500)

    def test_remove_item(self):
        item = ScheduleItem.objects.create(plan=self.plan, name='削除予定', card_type='free')
        resp = self.client.post(reverse('api_remove_item', args=[self.plan.pk, item.pk]))
        self.assertEqual(resp.json(), {'ok': True})
        self.assertFalse(ScheduleItem.objects.filter(pk=item.pk).exists())

    def test_non_owner_cannot_remove_item(self):
        item = ScheduleItem.objects.create(plan=self.plan, name='守られる予定', card_type='free')
        self.client.force_login(self.stranger)
        resp = self.client.post(reverse('api_remove_item', args=[self.plan.pk, item.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(ScheduleItem.objects.filter(pk=item.pk).exists())

    def test_reorder_updates_day_and_order(self):
        item1 = ScheduleItem.objects.create(plan=self.plan, name='A', card_type='free', day_number=1, order=0)
        item2 = ScheduleItem.objects.create(plan=self.plan, name='B', card_type='free', day_number=1, order=1)
        self._post_json(reverse('api_reorder', args=[self.plan.pk]), [
            {'id': item1.pk, 'day': 2, 'order': 0},
            {'id': item2.pk, 'day': 1, 'order': 0},
        ])
        item1.refresh_from_db()
        item2.refresh_from_db()
        self.assertEqual(item1.day_number, 2)
        self.assertEqual(item2.order, 0)

    def test_get_request_rejected_on_post_only_endpoints(self):
        resp = self.client.get(reverse('api_add_item', args=[self.plan.pk]))
        self.assertEqual(resp.status_code, 405)


class ApprovalFlowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='approvalowner', password='pass1234')
        Profile.objects.create(user=self.owner, home_address='x')
        self.member = User.objects.create_user(username='approvalmember', password='pass1234')
        Profile.objects.create(user=self.member, home_address='x')
        self.plan = TravelPlan.objects.create(user=self.owner, name='承認テスト')
        self.group = Group.objects.create(name='承認グループ', owner=self.owner)
        self.group.members.add(self.member)
        self.plan.group = self.group
        self.plan.save(update_fields=['group'])
        self.item = ScheduleItem.objects.create(
            plan=self.plan, name='観光', card_type='see', approval_enabled=True,
        )

    def _respond(self, status, comment=''):
        return self.client.post(
            reverse('api_set_response', args=[self.plan.pk, self.item.pk]),
            data=json.dumps({'status': status, 'comment': comment}),
            content_type='application/json',
        )

    def test_member_can_approve(self):
        self.client.force_login(self.member)
        resp = self._respond('approved')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(CardResponse.objects.filter(item=self.item, user=self.member, status='approved').exists())

    def test_response_is_locked_after_first_answer(self):
        self.client.force_login(self.member)
        self._respond('approved')
        resp = self._respond('rejected')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(CardResponse.objects.get(item=self.item, user=self.member).status, 'approved')

    def test_reject_comment_visible_only_to_owner(self):
        self.client.force_login(self.member)
        self._respond('rejected', comment='時間が合いません')

        self.client.force_login(self.owner)
        resp = self.client.get(reverse('plan_edit', args=[self.plan.pk]))
        self.assertContains(resp, '時間が合いません')

    def test_non_member_cannot_respond(self):
        outsider = User.objects.create_user(username='outsider', password='pass1234')
        self.client.force_login(outsider)
        resp = self._respond('approved')
        self.assertEqual(resp.status_code, 404)

    def test_cannot_respond_to_item_without_approval_enabled(self):
        plain_item = ScheduleItem.objects.create(plan=self.plan, name='自由時間', card_type='free')
        self.client.force_login(self.member)
        resp = self.client.post(
            reverse('api_set_response', args=[self.plan.pk, plain_item.pk]),
            data=json.dumps({'status': 'approved'}), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_owner_view_has_no_respond_buttons_but_member_view_does(self):
        # 'approve-btn'/'reject-btn' also appear as CSS class selectors in
        # <style>, so check for the rendered button's own text instead.
        self.client.force_login(self.owner)
        owner_resp = self.client.get(reverse('plan_edit', args=[self.plan.pk]))
        self.assertNotContains(owner_resp, '>承諾<')
        self.assertNotContains(owner_resp, '>拒否<')

        self.client.force_login(self.member)
        member_resp = self.client.get(reverse('plan_edit', args=[self.plan.pk]))
        self.assertContains(member_resp, '>承諾<')
        self.assertContains(member_resp, '>拒否<')

    def test_owner_view_shows_who_approved_and_rejected(self):
        second_member = User.objects.create_user(username='approvalmember2', password='pass1234')
        self.group.members.add(second_member)

        self.client.force_login(self.member)
        self._respond('approved')
        self.client.force_login(second_member)
        self._respond('rejected')

        self.client.force_login(self.owner)
        resp = self.client.get(reverse('plan_edit', args=[self.plan.pk]))
        self.assertContains(resp, 'approvalmember')
        self.assertContains(resp, 'approvalmember2')

    def test_tally_denominator_excludes_owner_so_it_can_reach_full_completion(self):
        # The group here has exactly one real member (self.member); the owner
        # can never respond (no UI for it), so the tally must read "1/1", not
        # "1/2", once that one member has answered.
        self.client.force_login(self.member)
        self._respond('approved')

        self.client.force_login(self.owner)
        days, days_data = _build_days_data(self.plan, user=self.owner)
        item = next(i for day in days_data for i in day['items'] if i.pk == self.item.pk)
        self.assertEqual(item.member_count, 1)
        self.assertEqual(item.approved_count, 1)

    def test_stray_owner_response_does_not_inflate_tally_or_show_as_a_badge(self):
        # A response the owner left behind from before their respond UI was
        # removed shouldn't count as a real member response anywhere.
        CardResponse.objects.create(item=self.item, user=self.owner, status='approved')

        self.client.force_login(self.owner)
        days, days_data = _build_days_data(self.plan, user=self.owner)
        item = next(i for day in days_data for i in day['items'] if i.pk == self.item.pk)
        self.assertEqual(item.approved_count, 0)
        self.assertEqual(item.responses_detail, [])

        # 'responder-badge' also appears as a CSS class selector in <style>,
        # so check for the owner's name never being rendered as a badge instead.
        resp = self.client.get(reverse('plan_edit', args=[self.plan.pk]))
        self.assertNotContains(resp, '✅ approvalowner')
        self.assertNotContains(resp, '🚫 approvalowner')

    def test_owner_gets_notified_on_approval_not_just_rejection(self):
        self.client.force_login(self.member)
        self._respond('approved')

        self.client.force_login(self.owner)
        resp = self.client.get(reverse('notifications'))
        kinds = [(n['kind'], n.get('status')) for n in resp.context['notifications']]
        self.assertIn(('response', 'approved'), kinds)

    def test_owner_unread_count_includes_approvals(self):
        self.client.force_login(self.member)
        self._respond('approved')

        self.client.force_login(self.owner)
        resp = self.client.get(reverse('top'))
        self.assertEqual(resp.context['unread_notification_count'], 1)

    def test_owner_can_mark_approval_notification_read(self):
        self.client.force_login(self.member)
        self._respond('approved')
        response_obj = CardResponse.objects.get(item=self.item, user=self.member)

        self.client.force_login(self.owner)
        self.client.post(reverse('notification_read', args=[response_obj.pk]))
        response_obj.refresh_from_db()
        self.assertTrue(response_obj.is_read)

    def test_notification_read_redirects_to_the_items_own_day(self):
        self.item.day_number = 2
        self.item.save(update_fields=['day_number'])
        self.client.force_login(self.member)
        self._respond('approved')
        response_obj = CardResponse.objects.get(item=self.item, user=self.member)

        self.client.force_login(self.owner)
        resp = self.client.post(reverse('notification_read', args=[response_obj.pk]))
        expected = reverse('plan_edit', args=[self.plan.pk]) + f'?day=2&item={self.item.pk}'
        self.assertRedirects(resp, expected)

    def test_plan_edit_exposes_focus_day_and_item_from_query_params(self):
        self.client.force_login(self.owner)
        url = reverse('plan_edit', args=[self.plan.pk]) + f'?day=2&item={self.item.pk}'
        resp = self.client.get(url)
        self.assertContains(resp, f'const FOCUS_DAY = 2;')
        self.assertContains(resp, f'const FOCUS_ITEM = {self.item.pk};')

    def test_plan_edit_ignores_malformed_focus_query_params(self):
        self.client.force_login(self.owner)
        url = reverse('plan_edit', args=[self.plan.pk]) + '?day=notanumber&item='
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'const FOCUS_DAY = null;')
        self.assertContains(resp, 'const FOCUS_ITEM = null;')

    def test_read_response_notification_disappears_from_the_list(self):
        self.client.force_login(self.member)
        self._respond('approved')
        response_obj = CardResponse.objects.get(item=self.item, user=self.member)

        self.client.force_login(self.owner)
        resp = self.client.get(reverse('notifications'))
        self.assertEqual(len(resp.context['notifications']), 1)

        self.client.post(reverse('notification_read', args=[response_obj.pk]))
        resp2 = self.client.get(reverse('notifications'))
        self.assertEqual(len(resp2.context['notifications']), 0)

    def test_member_sees_pending_approval_until_they_respond(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse('notifications'))
        pending_ids = [item.pk for item in resp.context['pending_approvals']]
        self.assertIn(self.item.pk, pending_ids)

        self._respond('approved')
        resp2 = self.client.get(reverse('notifications'))
        pending_ids2 = [item.pk for item in resp2.context['pending_approvals']]
        self.assertNotIn(self.item.pk, pending_ids2)

    def test_pending_approval_link_includes_day_and_item(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse('notifications'))
        expected = f'/plan/{self.plan.pk}/edit/?day={self.item.day_number}&item={self.item.pk}'
        self.assertContains(resp, expected)

    def test_member_unread_count_includes_pending_approval(self):
        self.client.force_login(self.member)
        resp = self.client.get(reverse('top'))
        self.assertEqual(resp.context['unread_notification_count'], 1)

    def test_owner_does_not_see_their_own_item_as_pending_approval(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('notifications'))
        self.assertEqual(len(resp.context['pending_approvals']), 0)

    def test_non_group_member_does_not_see_pending_approval(self):
        outsider = User.objects.create_user(username='approvaloutsider', password='pass1234')
        self.client.force_login(outsider)
        resp = self.client.get(reverse('notifications'))
        self.assertEqual(len(resp.context['pending_approvals']), 0)

    def test_owner_is_not_notified_of_their_own_response(self):
        # The UI no longer offers approve/reject to the owner, but the API
        # itself doesn't forbid it (owner always passes can_view); make sure
        # that edge case still never self-notifies.
        self.client.force_login(self.owner)
        self._respond('approved')

        resp = self.client.get(reverse('notifications'))
        self.assertEqual(len(resp.context['notifications']), 0)

        top_resp = self.client.get(reverse('top'))
        self.assertEqual(top_resp.context['unread_notification_count'], 0)


class GroupTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='groupowner', password='pass1234')
        Profile.objects.create(user=self.owner, home_address='x')
        self.member = User.objects.create_user(username='groupmember', password='pass1234')
        Profile.objects.create(user=self.member, home_address='x')
        self.client.force_login(self.owner)

    def test_create_group_sets_owner(self):
        self.client.post(reverse('group_new'), {'name': '家族旅行'})
        group = Group.objects.get(name='家族旅行')
        self.assertEqual(group.owner, self.owner)

    def test_owner_can_add_member(self):
        group = Group.objects.create(name='友人', owner=self.owner)
        self.client.post(reverse('group_detail', args=[group.pk]), {'username': 'groupmember'})
        self.assertTrue(group.is_member(self.member))

    def test_adding_nonexistent_username_shows_error(self):
        group = Group.objects.create(name='友人2', owner=self.owner)
        resp = self.client.post(reverse('group_detail', args=[group.pk]), {'username': 'ghost'})
        self.assertContains(resp, 'そのユーザー名は見つかりません')

    def test_adding_owner_as_member_shows_error(self):
        group = Group.objects.create(name='友人3', owner=self.owner)
        resp = self.client.post(reverse('group_detail', args=[group.pk]), {'username': 'groupowner'})
        self.assertContains(resp, 'グループのオーナーはすでにメンバーです')

    def test_non_member_cannot_view_group(self):
        group = Group.objects.create(name='非公開グループ', owner=self.owner)
        self.client.force_login(self.member)
        resp = self.client.get(reverse('group_detail', args=[group.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_non_owner_cannot_remove_member(self):
        group = Group.objects.create(name='友人4', owner=self.owner)
        group.members.add(self.member)
        self.client.force_login(self.member)
        resp = self.client.post(reverse('group_remove_member', args=[group.pk, self.owner.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_owner_cannot_leave_own_group(self):
        group = Group.objects.create(name='友人5', owner=self.owner)
        resp = self.client.post(reverse('group_leave', args=[group.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_member_can_leave_group(self):
        group = Group.objects.create(name='友人6', owner=self.owner)
        group.members.add(self.member)
        self.client.force_login(self.member)
        self.client.post(reverse('group_leave', args=[group.pk]))
        self.assertFalse(group.is_member(self.member))

    def test_only_owner_can_delete_group(self):
        group = Group.objects.create(name='友人7', owner=self.owner)
        group.members.add(self.member)
        self.client.force_login(self.member)
        resp = self.client.post(reverse('group_delete', args=[group.pk]))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Group.objects.filter(pk=group.pk).exists())

        self.client.force_login(self.owner)
        self.client.post(reverse('group_delete', args=[group.pk]))
        self.assertFalse(Group.objects.filter(pk=group.pk).exists())

    def test_group_chat_message_send_and_list(self):
        group = Group.objects.create(name='チャットグループ', owner=self.owner)
        group.members.add(self.member)
        self.client.force_login(self.member)
        resp = self.client.post(
            reverse('api_group_messages', args=[group.pk]),
            data=json.dumps({'text': 'こんにちは'}), content_type='application/json',
        )
        texts = [m['text'] for m in resp.json()['messages']]
        self.assertIn('こんにちは', texts)

    def test_non_member_cannot_send_chat_message(self):
        group = Group.objects.create(name='非公開チャット', owner=self.owner)
        outsider = User.objects.create_user(username='chatoutsider', password='pass1234')
        self.client.force_login(outsider)
        resp = self.client.post(
            reverse('api_group_messages', args=[group.pk]),
            data=json.dumps({'text': '侵入'}), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)


class LikeAndNotificationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='likeowner', password='pass1234')
        Profile.objects.create(user=self.owner, home_address='x')
        self.fan = User.objects.create_user(username='likefan', password='pass1234')
        Profile.objects.create(user=self.fan, home_address='x')
        self.plan = TravelPlan.objects.create(user=self.owner, name='いいねテスト')
        # Liking requires can_view, which (besides the owner) only group members
        # have, so the "fan" needs to share a group with the plan to like it.
        group = Group.objects.create(name='いいねグループ', owner=self.owner)
        group.members.add(self.fan)
        self.plan.group = group
        self.plan.save(update_fields=['group'])

    def test_other_user_can_like_and_unlike(self):
        self.client.force_login(self.fan)
        self.client.post(reverse('plan_like_toggle', args=[self.plan.pk]))
        self.assertTrue(PlanLike.objects.filter(plan=self.plan, user=self.fan).exists())
        self.client.post(reverse('plan_like_toggle', args=[self.plan.pk]))
        self.assertFalse(PlanLike.objects.filter(plan=self.plan, user=self.fan).exists())

    def test_owner_can_like_own_plan_but_it_generates_no_notification(self):
        self.client.force_login(self.owner)
        self.client.post(reverse('plan_like_toggle', args=[self.plan.pk]))
        self.assertTrue(PlanLike.objects.filter(plan=self.plan, user=self.owner).exists())
        resp = self.client.get(reverse('notifications'))
        self.assertEqual(len(resp.context['notifications']), 0)

    def test_like_by_other_user_shows_up_as_notification_for_owner(self):
        self.client.force_login(self.fan)
        self.client.post(reverse('plan_like_toggle', args=[self.plan.pk]))
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('notifications'))
        self.assertEqual(len(resp.context['notifications']), 1)

    def test_marking_like_notification_read_only_by_plan_owner(self):
        like = PlanLike.objects.create(plan=self.plan, user=self.fan)
        self.client.force_login(self.fan)
        resp = self.client.post(reverse('plan_like_read', args=[like.pk]))
        self.assertEqual(resp.status_code, 404)
        like.refresh_from_db()
        self.assertFalse(like.is_read)

        self.client.force_login(self.owner)
        self.client.post(reverse('plan_like_read', args=[like.pk]))
        like.refresh_from_db()
        self.assertTrue(like.is_read)

    def test_read_like_notification_disappears_from_the_list(self):
        like = PlanLike.objects.create(plan=self.plan, user=self.fan)
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('notifications'))
        self.assertEqual(len(resp.context['notifications']), 1)

        self.client.post(reverse('plan_like_read', args=[like.pk]))
        resp2 = self.client.get(reverse('notifications'))
        self.assertEqual(len(resp2.context['notifications']), 0)


class ShareViewTests(TestCase):
    def test_share_link_viewable_without_login(self):
        owner = User.objects.create_user(username='shareowner', password='pass1234')
        plan = TravelPlan.objects.create(user=owner, name='共有プラン')
        resp = Client().get(reverse('plan_share', args=[plan.share_token]))
        self.assertEqual(resp.status_code, 200)

    def test_unknown_share_token_is_404(self):
        resp = Client().get(reverse('plan_share', args=[uuid.uuid4()]))
        self.assertEqual(resp.status_code, 404)


class PlanMapHomeAddressResolutionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='mapowner', password='pass1234')
        Profile.objects.create(user=self.owner, home_address='大阪府高槻市大蔵司')
        self.plan = TravelPlan.objects.create(user=self.owner, name='地図テスト')
        self.client.force_login(self.owner)

    def test_home_label_resolves_to_registered_address_for_geocoding(self):
        ScheduleItem.objects.create(
            plan=self.plan, name='車', card_type='move', day_number=1,
            from_location='自宅', to_location='神戸空港',
        )
        resp = self.client.get(reverse('plan_map', args=[self.plan.pk]))
        locations = resp.context['locations']
        home_loc = next(l for l in locations if l['label'] == '自宅')
        self.assertEqual(home_loc['query'], '大阪府高槻市大蔵司')

    def test_legacy_family_label_also_resolves(self):
        ScheduleItem.objects.create(
            plan=self.plan, name='車', card_type='move', day_number=1,
            from_location='家', to_location='神戸空港',
        )
        resp = self.client.get(reverse('plan_map', args=[self.plan.pk]))
        locations = resp.context['locations']
        home_loc = next(l for l in locations if l['label'] == '家')
        self.assertEqual(home_loc['query'], '大阪府高槻市大蔵司')

    def test_home_label_without_registered_address_falls_back_to_label(self):
        no_address_owner = User.objects.create_user(username='noaddr', password='pass1234')
        Profile.objects.create(user=no_address_owner, home_address='')
        plan = TravelPlan.objects.create(user=no_address_owner, name='住所未設定プラン')
        ScheduleItem.objects.create(
            plan=plan, name='車', card_type='move', day_number=1,
            from_location='自宅', to_location='神戸空港',
        )
        self.client.force_login(no_address_owner)
        resp = self.client.get(reverse('plan_map', args=[plan.pk]))
        home_loc = next(l for l in resp.context['locations'] if l['label'] == '自宅')
        self.assertEqual(home_loc['query'], '自宅')

    def test_regular_location_is_unaffected(self):
        ScheduleItem.objects.create(plan=self.plan, name='清水寺', card_type='see', day_number=1)
        resp = self.client.get(reverse('plan_map', args=[self.plan.pk]))
        loc = resp.context['locations'][0]
        self.assertEqual(loc['label'], '清水寺')
        self.assertEqual(loc['query'], '清水寺')


class SecurityTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='secowner', password='pass1234')
        Profile.objects.create(user=self.owner, home_address='x')
        self.plan = TravelPlan.objects.create(user=self.owner, name='セキュリティテスト')

    def test_anonymous_user_redirected_to_login(self):
        url = reverse('plan_edit', args=[self.plan.pk])
        resp = self.client.get(url)
        self.assertRedirects(resp, f"{reverse('login')}?next={url}")

    def test_post_without_csrf_token_is_rejected(self):
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.force_login(self.owner)
        resp = strict_client.post(reverse('plan_toggle_warikan', args=[self.plan.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_require_post_endpoints_reject_get(self):
        self.client.force_login(self.owner)
        for name, args in [
            ('plan_like_toggle', [self.plan.pk]),
            ('plan_toggle_warikan', [self.plan.pk]),
            ('plan_set_participants', [self.plan.pk]),
        ]:
            resp = self.client.get(reverse(name, args=args))
            self.assertEqual(resp.status_code, 405, f'{name} should reject GET')

    def test_notification_bearing_pages_are_never_cached(self):
        # The notification badge/list must always reflect fresh state after a
        # reload, so the browser must never be allowed to serve a cached copy
        # of these pages (which previously made completed items look stuck).
        self.client.force_login(self.owner)
        for name, args in [
            ('top', []),
            ('notifications', []),
            ('plan_edit', [self.plan.pk]),
        ]:
            resp = self.client.get(reverse(name, args=args))
            self.assertIn('no-store', resp.headers.get('Cache-Control', ''), f'{name} should be marked no-store')
