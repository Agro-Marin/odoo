import base64
import json
import logging
import math
from ast import literal_eval
from urllib.parse import urlencode

import werkzeug
from dateutil.relativedelta import relativedelta

from odoo import _, fields, http, tools
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.http import Response, request
from odoo.tools import consteq, email_normalize_all
from odoo.tools.translate import LazyTranslate
from odoo.tools.urls import keep_query

from odoo.addons.website.controllers.main import QueryURL
from odoo.addons.website.models.ir_http import sitemap_qs2dom
from odoo.addons.website_profile.controllers.main import WebsiteProfile

_lt = LazyTranslate(__name__)
_logger = logging.getLogger(__name__)


def handle_wslide_error(exception, **kwargs):
    if isinstance(exception, AccessError):
        return request.redirect("/slides?invite_error=no_rights", 302)
    return None


class WebsiteSlides(WebsiteProfile):
    _slides_per_page = 12
    _slides_per_aside = 20
    _slides_per_category = 3
    _channel_order_by_criterion = {
        "vote": "total_votes desc",
        "view": "total_views desc",
        "date": "create_date desc",
    }

    def sitemap_slide(env, rule, qs):  # noqa: N805 -- sitemap callback, first arg is the env
        Channel = env["slide.channel"]
        dom = sitemap_qs2dom(qs=qs, route="/slides/", field=Channel._rec_name)
        dom &= env["website"].get_current_website().website_domain()
        for channel in Channel.search(dom):
            loc = "/slides/%s" % env["ir.http"]._slug(channel)
            if not qs or qs.lower() in loc:
                yield {"loc": loc}

    def _slide_render_context_base(self):
        return {
            # current user info
            "user": request.env.user,
            "is_public_user": request.website.is_public_user(),
            # tools
            "_slugify_tags": self._slugify_tags,
        }

    # SLIDE UTILITIES
    # --------------------------------------------------

    def _fetch_slide(self, slide_id):
        slide = request.env["slide.slide"].browse(int(slide_id)).exists()
        if not slide:
            return {"error": "slide_wrong"}
        if not slide.has_access("read"):
            return {"error": "slide_access"}
        return {"slide": slide}

    def _set_viewed_slide(self, slide, quiz_attempts_inc=False):
        if not slide.channel_id.is_member:
            if not isinstance(request.session.get("viewed_slides"), dict):
                # Compatibility layer with Odoo 15.0,
                # where `viewed_slides` are stored as `list` in sessions.
                # For performance concerns, `viewed_slides` is changed to a dict,
                # but sessions coming from Odoo 15.0 after an upgrade should still be compatible.
                # This compatibility layer regarding `viewed_slides` must remain from Odoo 16.0 and above,
                # as this is possible to do a jump of multiple versions in one go,
                # and carry the sessions with the upgrade.
                # e.g. upgrade from Odoo 15.0 to 18.0.
                request.session["viewed_slides"] = dict.fromkeys(
                    request.session.get("viewed_slides", []), 1
                )
            viewed_slides = request.session["viewed_slides"]
            # Convert `slide.id` to string is necessary because of the JSON format of the session
            slide_id = str(slide.id)
            if slide_id not in viewed_slides:
                if slide._increment_fields_skiplock("public_views", "total_views"):
                    viewed_slides[slide_id] = 1
                    request.session.touch()
        else:
            slide.action_set_viewed(quiz_attempts_inc=quiz_attempts_inc)
        return True

    def _slide_mark_completed(self, slide):
        # quiz use their specific mechanism to be marked as done
        if slide.slide_category == "quiz" or slide.has_questions:
            raise UserError(
                _(
                    "Slide with questions must be marked as done when submitting all good answers "
                )
            )
        if not slide.can_self_mark_completed:
            raise werkzeug.exceptions.Forbidden(
                _("This slide can not be marked as completed.")
            )
        slide.action_mark_completed()

    def _slide_mark_uncompleted(self, slide):
        if not slide.can_self_mark_uncompleted:
            raise werkzeug.exceptions.Forbidden(
                _("This slide can not be marked as uncompleted.")
            )
        slide.action_mark_uncompleted()

    # ------------------------------------------------------------------
    # THE SUDO BOUNDARY
    #
    # `can_upload` / `can_publish` are *business* rights: slide.channel grants
    # them to the course responsible whatever groups they hold, on a `user_id`
    # field with no domain. The ACLs are *technical* rights and grant that same
    # person nothing -- slide.slide, slide.slide.partner and slide.channel.tag
    # are all eLearning-Officer-only, and the officer rules are scoped to
    # courses they are responsible for.
    #
    # The two systems disagree, and the module used to paper over the gap one
    # route at a time: of seven publisher routes, two happened to call .sudo()
    # and worked, and five did not and raised AccessError for a course
    # responsible holding only base.group_user. `sudo` was the accidental
    # differentiator rather than a decision.
    #
    # These two helpers state the decision once. Authorization is the business
    # right, checked here and only here; the ORM call that follows runs as sudo
    # because the ACL cannot express "the responsible of this course".
    # ------------------------------------------------------------------

    def _check_channel_publisher(self, channel, require_upload=True):
        """Authorize a publisher action on ``channel``, then hand back sudo.

        :param require_upload: also demand ``can_upload``. Publishing implies
          uploading everywhere except the (sudo-created) upload route itself,
          so this is the default.
        :raise werkzeug.exceptions.Forbidden: if the caller may not publish.
        :return: ``channel`` in a sudo environment.
        """
        if not channel.can_publish or (require_upload and not channel.can_upload):
            raise werkzeug.exceptions.Forbidden(
                channel._get_can_publish_error_message()
            )
        return channel.sudo()

    def _browse_existing(self, model, record_id):
        """Resolve a client-supplied id, or 404.

        Historical clients send ids as strings, and `browse("19")` iterates the
        string into the bogus ids ('1', '9') rather than failing; a stale id
        reaches the ORM as a phantom record and surfaces as a 500 several lines
        later. 75fc9e0238d fixed one route this way; the rest kept the shape.
        """
        try:
            record_id = int(record_id)
        except (TypeError, ValueError) as error:
            raise werkzeug.exceptions.NotFound from error
        record = request.env[model].browse(record_id).exists()
        if not record:
            raise werkzeug.exceptions.NotFound
        return record

    def _get_own_slide_progress_sudo(self, slide):
        """The caller's *own* ``slide.slide.partner`` row, as sudo.

        A learner cannot read or write their own progress row under their own
        rights -- the model is officer-only -- which is why every model-side
        path (`_action_set_viewed`, `_action_mark_completed`) already sudoes.
        The domain pins ``partner_id`` to the caller, so sudo widens nothing.
        """
        return (
            request.env["slide.slide.partner"]
            .sudo()
            .search(
                [
                    ("slide_id", "=", slide.id),
                    ("partner_id", "=", request.env.user.partner_id.id),
                ]
            )
        )

    def _get_slide_detail(self, slide):
        base_domain = self._get_channel_slides_base_domain(slide.channel_id)
        category_data = slide.channel_id._get_categorized_slides(
            base_domain,
            order=request.env["slide.slide"]._order_by_strategy["sequence"],
            force_void=True,
        )

        if slide.channel_id.channel_type == "documentation":
            most_viewed_slides = request.env["slide.slide"].search(
                base_domain, limit=self._slides_per_aside, order="total_views desc"
            )
            related_domain = base_domain & Domain(
                "category_id", "=", slide.category_id.id
            )
            related_slides = request.env["slide.slide"].search(
                related_domain, limit=self._slides_per_aside
            )
        else:
            most_viewed_slides, related_slides = (
                request.env["slide.slide"],
                request.env["slide.slide"],
            )

        channel_slides_ids = slide.channel_id.slide_content_ids.ids
        slide_index = channel_slides_ids.index(slide.id)
        previous_slide = (
            slide.channel_id.slide_content_ids[slide_index - 1]
            if slide_index > 0
            else None
        )
        next_slide = (
            slide.channel_id.slide_content_ids[slide_index + 1]
            if slide_index < len(channel_slides_ids) - 1
            else None
        )

        render_values = self._slide_render_context_base()
        render_values.update(
            {
                # slide
                "slide": slide,
                "main_object": slide,
                "most_viewed_slides": most_viewed_slides,
                "related_slides": related_slides,
                "previous_slide": previous_slide,
                "next_slide": next_slide,
                "category_data": category_data,
                # rating and comments
                "comments": slide.website_message_ids or [],
            }
        )

        # allow rating and comments
        if slide.channel_id.allow_comment:
            render_values.update(
                {
                    "message_post_pid": request.env.user.partner_id.id,
                }
            )

        return render_values

    def _get_slide_quiz_partner_info(self, slide, quiz_done=False):
        return slide._compute_quiz_info(
            request.env.user.partner_id, quiz_done=quiz_done
        )[slide.id]

    def _get_slide_quiz_data(self, slide):
        # Who may see which answer is correct, and its comment. This is the read
        # half of quiz editing and it must name the same right as the write half
        # (slide_quiz_question_add_or_update), or a publisher loads the edit form
        # blind: `is_correct` arrives as None, no radio is preselected, and
        # saving stores is_correct=False on every answer, which makes the quiz
        # unpassable. The two conditions were also mutually exclusive -- the edit
        # pencil renders only while `not slide_completed`, and the old gate
        # released `is_correct` only once completed -- so for anyone outside
        # website.group_website_designer it failed every time. Neither eLearning
        # group implies that one; only `admin` holds it, which is why it looked
        # fine in every demo database.
        is_editor = slide.channel_id.can_publish
        slides_resources = (
            slide.slide_resource_ids if slide.channel_id.is_member else []
        )
        # The quiz survey is an implementation detail of the slide, not a
        # survey the visitor owns; access is already gated by slide/channel
        # read rights. Read it sudo — as the rest of the module does (see
        # _check_quiz_survey and slide_quiz_question_add_or_update) — so
        # course members without survey groups don't hit an AccessError.
        survey_questions = (
            slide.survey_id.sudo().question_ids.filtered(lambda q: not q.is_page)
            if slide.survey_id
            else []
        )
        values = {
            "slide_description": slide.description,
            "slide_questions": [
                {
                    "answer_ids": [
                        {
                            "comment": answer.comment if is_editor else None,
                            "id": answer.id,
                            "is_correct": answer.is_correct
                            if slide.user_has_completed or is_editor
                            else None,
                            "text_value": answer.value,
                        }
                        for answer in question.sudo().suggested_answer_ids
                    ],
                    "id": question.id,
                    "question": question.title,
                }
                for question in survey_questions
            ],
            "slide_resource_ids": [
                {
                    "display_name": resource.display_name,
                    "download_url": resource.download_url,
                    "id": resource.id,
                    "link": resource.link,
                    "resource_type": resource.resource_type,
                }
                for resource in slides_resources
            ],
        }
        if "slide_answer_quiz" in request.session:
            slide_answer_quiz = json.loads(request.session["slide_answer_quiz"])
            if str(slide.id) in slide_answer_quiz:
                values["session_answers"] = slide_answer_quiz[str(slide.id)]
        values.update(self._get_slide_quiz_partner_info(slide))
        return values

    def _get_new_slide_category_values(self, channel, name):
        return {
            "name": name,
            "channel_id": channel.id,
            "is_category": True,
            "is_published": True,
            "sequence": channel.slide_ids[-1]["sequence"] + 1
            if channel.slide_ids
            else 1,
        }

    # CHANNEL UTILITIES
    # --------------------------------------------------

    def _get_channel_slides_base_domain(self, channel):
        """base domain when fetching slide list data related to a given channel

        * website related domain, and restricted to the channel and is not a
          category slide (behavior is different from classic slide);
        * if publisher: everything is ok;
        * if not publisher but has user: either slide is published, either
          current user is the one that uploaded it;
        * if not publisher and public: published;
        """
        base_domain = (
            request.website.website_domain()
            & Domain("channel_id", "=", channel.id)
            & Domain("is_category", "=", False)
        )
        if not channel.can_publish:
            if request.website.is_public_user():
                base_domain &= Domain("website_published", "=", True)
            else:
                base_domain &= Domain("website_published", "=", True) | Domain(
                    "user_id", "=", request.env.user.id
                )
        return base_domain

    # The keys the templates actually read off channel_progress. This used to
    # be `slide_partner.read()[0]` per membership -- every column of the model,
    # per row, on every course and lesson page -- plus a `quiz_gain` key that no
    # Python, XML or JS anywhere reads.
    _CHANNEL_PROGRESS_FIELDS = ("completed", "quiz_attempts_count", "vote")

    def _get_channel_progress(self, channel, include_quiz=False):
        """Replacement to user_progress. Both may exist in some transient state."""
        slides = (
            request.env["slide.slide"].sudo().search([("channel_id", "=", channel.id)])
        )
        channel_progress = {sid: {} for sid in slides.ids}
        if not request.env.user._is_public() and channel.is_member:
            for progress in (
                request.env["slide.slide.partner"]
                .sudo()
                .search_read(
                    [
                        ("channel_id", "=", channel.id),
                        ("partner_id", "=", request.env.user.partner_id.id),
                        ("slide_id", "in", slides.ids),
                    ],
                    ["slide_id", *self._CHANNEL_PROGRESS_FIELDS],
                )
            ):
                slide_id = progress.pop("slide_id")[0]
                channel_progress[slide_id].update(progress)

        if include_quiz:
            quiz_info = slides._compute_quiz_info(
                request.env.user.partner_id, quiz_done=False
            )
            for slide_id, slide_info in quiz_info.items():
                channel_progress[slide_id].update(slide_info)

        return channel_progress

    def _channel_remove_session_answers(self, channel, slide=False):
        """Will remove the answers saved in the session for a specific channel / slide."""

        if "slide_answer_quiz" not in request.session:
            return

        slides_domain = [("channel_id", "=", channel.id)]
        if slide:
            slides_domain = Domain.AND([slides_domain, [("id", "=", slide.id)]])
        slides = request.env["slide.slide"].search(slides_domain)

        session_slide_answer_quiz = json.loads(request.session["slide_answer_quiz"])
        for slide_id in slides.ids:
            session_slide_answer_quiz.pop(str(slide_id), None)
        request.session["slide_answer_quiz"] = json.dumps(session_slide_answer_quiz)

    def _prepare_collapsed_categories(
        self, categories_values, slide, next_category_to_open
    ):
        """Collapse the category if:
        - there is no category (the slides are uncategorized)
        - the category contains the current slide
        - the category is ongoing (has at least one slide completed but not all of its slides)
        - the category is the next one to be opened because the current one has just been completed
        """
        if request.env.user._is_public() or not slide.channel_id.is_member:
            return categories_values
        for category_dict in categories_values:
            category = category_dict.get("category")
            if (
                not category
                or slide in category.slide_ids
                or category == next_category_to_open
            ):
                category_dict["is_collapsed"] = True
            else:
                # collapse if category is ongoing
                slides_completion = category.slide_ids.mapped("user_has_completed")
                category_dict["is_collapsed"] = any(slides_completion) and not all(
                    slides_completion
                )
        return categories_values

    # TAG UTILITIES
    # --------------------------------------------------

    def _slugify_tags(self, tag_ids, toggle_tag_id=None):
        """Prepares a comma separated slugified tags for the sake of readable
        URLs.

        :param toggle_tag_id: add the tag being clicked (current_tag) to the already
          selected tags (tag_ids) as well as in URL; if tag is already selected
          by the user it is removed from the selected tags (and so from the URL);
        """
        tag_ids = list(tag_ids)  # required to avoid using the same list
        if toggle_tag_id and toggle_tag_id in tag_ids:
            tag_ids.remove(toggle_tag_id)
        elif toggle_tag_id:
            tag_ids.append(toggle_tag_id)
        return ",".join(
            request.env["ir.http"]._slug(tag)
            for tag in request.env["slide.channel.tag"].browse(tag_ids)
        )

    def _channel_search_tags_ids(self, search_tags):
        """Input: %5B4%5D"""
        ChannelTag = request.env["slide.channel.tag"]
        try:
            tag_ids = literal_eval(search_tags or "")
        except Exception:
            return ChannelTag
        # perform a search to filter on existing / valid tags implicitly
        return ChannelTag.search([("id", "in", tag_ids)]) if tag_ids else ChannelTag

    def _channel_search_tags_slug(self, search_tags):
        """Input: hotels-1,adventure-2"""
        return request.env["slide.channel.tag"]._search_by_slugs(search_tags)

    def _create_or_get_channel_tag(self, tag_id, group_id):
        """Resolve a SelectMenu value to a ``slide.channel.tag``.

        Returns a recordset, or ``{"error": ...}`` when the input cannot be
        resolved. Both callers must handle the dict.

        The tag and its group are created under the caller's own rights on
        purpose: tagging *your* course is a publisher action, but minting a tag
        in the site-wide taxonomy is not, and it stays behind the officer ACL.
        The AccessError that follows from that is turned into an error dict here
        rather than escaping as a 500.
        """
        if not tag_id:
            return request.env["slide.channel.tag"]
        # handle creation of new channel tag
        if tag_id[0] == 0:
            try:
                group_id = self._create_or_get_channel_tag_group_id(group_id)
                if not group_id:
                    return {"error": _('Missing "Tag Group" for creating a new "Tag".')}
                return request.env["slide.channel.tag"].create(
                    {
                        "name": tag_id[1]["name"],
                        "group_id": group_id,
                    }
                )
            except AccessError:
                return {
                    "error": _(
                        "You are not allowed to create new course tags. "
                        "Pick an existing one, or ask an eLearning officer."
                    )
                }
        return request.env["slide.channel.tag"].browse(tag_id[0]).exists()

    def _create_or_get_channel_tag_group_id(self, group_id):
        if not group_id:
            return False
        # handle creation of new channel tag group
        if group_id[0] == 0:
            return (
                request.env["slide.channel.tag.group"]
                .create(
                    {
                        "name": group_id[1]["name"],
                    }
                )
                .id
            )
        # use existing channel tag group
        return group_id[0]

    # --------------------------------------------------
    # SLIDE.CHANNEL MAIN / SEARCH
    # --------------------------------------------------

    def _slides_channel_user_values(self, compute_channels_my=True):
        """Get user slide values (challenge done, top user to compare to, ...)."""
        render_values = {}
        if compute_channels_my:
            if not request.env.user._is_public():
                channels_my_all = tools.lazy(
                    lambda: request.env["slide.channel"].search(
                        request.website.website_domain()
                        & Domain([("is_visible", "=", True), ("is_member", "=", True)])
                    )
                )
                # Order: Started but not finished > Not started > Finished
                channels_my = tools.lazy(
                    lambda: channels_my_all.filtered(
                        lambda channel: channel.is_member
                    ).sorted(
                        lambda channel: -1 if channel.completed else channel.completion,
                        reverse=True,
                    )
                )
            else:
                channels_my = request.env["slide.channel"]
            render_values["channels_my"] = channels_my

        achievements = tools.lazy(
            lambda: (
                request.env["gamification.badge.user"]
                .sudo()
                .search([("badge_id.is_published", "=", True)], limit=5)
            )
        )
        if request.env.user._is_public():
            challenges = None
            challenges_done = None
        else:
            challenges = tools.lazy(
                lambda: (
                    request.env["gamification.challenge"]
                    .sudo()
                    .search(
                        [
                            ("challenge_category", "=", "slides"),
                            ("reward_id.is_published", "=", True),
                        ],
                        order="id asc",
                        limit=5,
                    )
                )
            )
            challenges_done = tools.lazy(
                lambda: (
                    request.env["gamification.badge.user"]
                    .sudo()
                    .search(
                        [
                            ("challenge_id", "in", challenges.ids),
                            ("user_id", "=", request.env.user.id),
                            ("badge_id.is_published", "=", True),
                        ]
                    )
                    .mapped("challenge_id")
                )
            )

        users = tools.lazy(
            lambda: (
                request.env["res.users"]
                .sudo()
                .search(
                    [("karma", ">", 0), ("website_published", "=", True)],
                    limit=5,
                    order="karma desc",
                )
            )
        )

        render_values.update(
            {
                "achievements": achievements,
                "users": users,
                "top3_users": tools.lazy(self._get_top3_users),
                "challenges": challenges,
                "challenges_done": challenges_done,
                "search_tags": request.env["slide.channel.tag"],
                "slide_query_url": QueryURL("/slides", ["tag"]),
                "slugify_tags": self._slugify_tags,
            }
        )
        return render_values

    def _get_slide_channel_search_options(
        self, my=None, slug_tags=None, slide_category=None, **post
    ):
        return {
            "displayDescription": True,
            "displayDetail": False,
            "displayExtraDetail": False,
            "displayExtraLink": False,
            "displayImage": False,
            "allowFuzzy": not post.get("noFuzzy"),
            "my": my,
            "tag": slug_tags or post.get("tag"),
            "slide_category": slide_category,
        }

    def _has_slide_channel_search(
        self, my=None, slug_tags=None, slide_category=None, **post
    ):
        return (
            my or post.get("search") or slug_tags or post.get("tag") or slide_category
        )

    @http.route(
        [
            "/slides",
            "/slides/page/<int:page>",
            "/slides/tag/<string:slug_tags>",
            "/slides/tag/<string:slug_tags>/page/<int:page>",
        ],
        type="http",
        auth="public",
        website=True,
        sitemap=True,
        readonly=True,
        list_as_website_content=_lt("eLearning"),
    )
    def slides_channel(self, slide_category=None, slug_tags=None, my=0, page=1, **post):
        my = (
            1 if str(my) == "1" else 0
        )  # if in the URL parameters, it will be a string instead of a number
        if (
            slug_tags
            and slug_tags.count(",") > 0
            and request.httprequest.method == "GET"
            and not post.get("prevent_redirect")
        ):
            # Previously, the tags were searched using GET, which caused issues with crawlers (too many hits)
            # We replaced those with POST to avoid that, but it's not sufficient as bots "remember" crawled pages for a while
            # This permanent redirect is placed to instruct the bots that this page is no longer valid
            # TODO: remove in a few stable versions (v19?), including the "prevent_redirect" param in templates
            # Note: We allow a single tag to be GET, to keep crawlers & indexes on those pages
            # What we really want to avoid is combinatorial explosions
            return request.redirect("/slides", code=301)

        render_values = self.slides_channel_values(
            slide_category=slide_category, slug_tags=slug_tags, my=my, page=page, **post
        )
        if page > 1 and not render_values["channels"]:
            # Refining search may reduce results; if no results and not on page 1, reset to page 1.
            if slug_tags:
                return request.redirect(f"/slides/tag/{slug_tags}?{keep_query('*')}")
            return request.redirect(f"/slides?{keep_query('*')}")
        return request.render("website_slides.courses_home", render_values)

    def slides_channel_values(
        self, slide_category=None, slug_tags=None, my=0, page=None, page_size=12, **post
    ):
        """Home page displaying a list of courses displayed according to some
        criterion and search terms.

          :param string slide_category: if provided, filter the course to contain at
           least one slide of type 'slide_category'. Used notably to display courses
           with certifications;
          :param string slug_tags: if provided, filter the slide.channels having
            the tag(s) (in comma separated slugified form);
          :param bool my: if provided, filter the slide.channels for which the
           current user is a member of
          :param dict post: post parameters, including
          :param int|None page: The current page number. Set to None to disable pagination (default).
          :param int page_size: number of element per page

           * ``search``: filter on course description / name;
        """
        search_args = {
            "my": my,
            "slug_tags": slug_tags,
            "slide_category": slide_category,
            **post,
        }
        options = self._get_slide_channel_search_options(**search_args)
        search = post.get("search")
        order = self._channel_order_by_criterion.get(post.get("sorting"))
        search_count, details, fuzzy_search_term = request.website._search_with_fuzzy(
            "slide_channels_only",
            search,
            limit=page * page_size if page else 1000,
            order=order,
            options=options,
        )
        channels_all = details[0].get("results", request.env["slide.channel"])
        channels = (
            channels_all[(page - 1) * page_size : page * page_size]
            if page
            else channels_all
        )
        tag_groups = request.env["slide.channel.tag.group"].search(
            ["&", ("tag_ids", "!=", False), ("website_published", "=", True)]
        )
        if slug_tags:
            search_tags = self._channel_search_tags_slug(slug_tags)
        elif post.get("tags"):
            search_tags = self._channel_search_tags_ids(post["tags"])
        else:
            search_tags = request.env["slide.channel.tag"]

        render_values = self._slide_render_context_base()
        render_values.update(self._prepare_user_values(**post))
        render_values.update(
            self._slides_channel_user_values(
                compute_channels_my=not self._has_slide_channel_search(**search_args)
            )
        )
        render_values.update(
            {
                "channels": channels,
                "tag_groups": tag_groups,
                "search_term": fuzzy_search_term or search,
                "original_search": fuzzy_search_term and search,
                "search_slide_category": slide_category,
                "search_my": my,
                "search_tags": search_tags,
                "search_count": search_count,
                "top3_users": self._get_top3_users(),
                "slugify_tags": self._slugify_tags,
                "slide_query_url": QueryURL("/slides", ["tag"]),
                "pager": request.website.pager(
                    url=request.httprequest.path.partition("/page/")[0],
                    url_args=request.httprequest.args.to_dict(),
                    total=search_count,
                    page=page,
                    step=page_size,
                    scope=3,
                )
                if page
                else False,
            }
        )

        return render_values

    def _prepare_additional_channel_values(self, values, **kwargs):
        return values

    def _get_top3_users(self):
        return (
            request.env["res.users"]
            .sudo()
            .search_read(
                [("karma", ">", 0), ("website_published", "=", True)],
                ["id"],
                limit=3,
                order="karma desc",
            )
        )

    def _get_user_slide_authorization(self, slide_id):
        """Get authorization status for the current user to access the given slide along with some data.
        :return: Dict in the form:
        {
            'status': authorized|not_found|not_authorized,
            'slide': the slide corresponding to the slide_id (only if status != 'not_found')
            'channel_id': id of the channel containing the slide (only if status != 'not_found')
        }
        """
        # `browse()` never raises, so the inner try/except that used to sit here
        # was dead and "not_found" was unreachable -- a deleted id reached
        # `slide.sudo().channel_id` and 404'd only because MissingError escaped
        # from there. Decide existence up front instead.
        slide_sudo = request.env["slide.slide"].sudo().browse(slide_id).exists()
        if not slide_sudo:
            return {"status": "not_found"}

        slide = request.env["slide.slide"].browse(slide_sudo.id)
        status = "authorized" if slide.has_access("read") else "not_authorized"
        return {
            "status": status,
            "slide": slide_sudo if status == "not_authorized" else slide,
            "channel_id": slide_sudo.channel_id.id,
        }

    @http.route(
        [
            "/slides/<int:channel_id>",
            "/slides/<int:channel_id>/category/<int:category_id>",
            "/slides/<int:channel_id>/category/<int:category_id>/page/<int:page>",
            '/slides/<model("slide.channel"):channel>',
            '/slides/<model("slide.channel"):channel>/page/<int:page>',
            '/slides/<model("slide.channel"):channel>/tag/<model("slide.tag"):tag>',
            '/slides/<model("slide.channel"):channel>/tag/<model("slide.tag"):tag>/page/<int:page>',
            '/slides/<model("slide.channel"):channel>/category/<model("slide.slide"):category>',
            '/slides/<model("slide.channel"):channel>/category/<model("slide.slide"):category>/page/<int:page>',
        ],
        type="http",
        auth="public",
        website=True,
        sitemap=sitemap_slide,
        handle_params_access_error=handle_wslide_error,
        readonly=True,
    )
    def channel(
        self,
        channel=False,
        channel_id=False,
        category=None,
        category_id=False,
        tag=None,
        page=1,
        slide_category=None,
        uncategorized=False,
        sorting=None,
        search=None,
        **kw,
    ):
        """Will return the rendered page of a course, with optional parameters allowing customization:

        :param channel: slide.channel to be rendered.
        :param channel_id: id of the rendered channel. (*)
        :param category: slide.slide (should be a category). Filter contents to those
            below this category (= section).
        :param category_id: id of the desired slide.slide category. (*)
        :param tag: slide.tag used to filter contents.
        :param slide_category: one of the values of linked selection field.
            Filter to this category of slides (video, article...)
        :param uncategorized: To set to True to access all slides outside of any slide.slide category.
        :param sorting: string defining the way to sort contents. ('most_voted', ...)
        :param search: string of the user search in the search bar.
        :param kw.invite_partner_id: id of the invited partner. (**)
        :param kw.invite_hash: string hash based on course and partner. (**)

        (*) Should be used for preview of invited attendees only. A 403 error could occur when using
            channel and category, if their access to models is denied. The generic shared course link
            uses channel_id as well, for the same reason.
        (**) Those are used to check and give invited attendees the access to the course and
            allow them browing its list of contents.
        """
        invite_partner_id = (
            int(kw["invite_partner_id"]) if kw.get("invite_partner_id") else False
        )
        invite_hash = kw.get("invite_hash")
        valid_invite_values = {}

        # Invitation data processing
        if (
            request.website.is_public_user()
            and invite_partner_id
            and invite_hash
            and channel_id
            and not channel
        ):
            valid_invite_values = self._get_channel_values_from_invite(
                channel_id, invite_hash, invite_partner_id
            )
            if valid_invite_values.get("invite_preview"):
                channel = valid_invite_values.get("invite_channel")
                valid_invite_values["pager_args"] = {
                    "invite_hash": invite_hash,
                    "invite_partner_id": invite_partner_id,
                }

        if channel_id < 0:
            # the string part of the channel "slugification" can be blank
            # meaning it can be "/slides/taking-care-of-trees-2" OR just "/slides/-2" if the first part is blank
            # as we use a IntConverter on the route definition, this will pick up a negative ID
            # (the IntConverter is necessary as we want a custom page in case the user can't access the course)
            channel_id = abs(channel_id)

        # Check access rights.
        # `if channel_id and ...` skipped id 0, which the IntConverter matches
        # happily: /slides/0 left `channel` as the boolean False and the next
        # line called `.has_access` on it -- a 500 on a publicly reachable URL.
        # Test against the parameter being *given*, not against it being truthy.
        if not channel:
            channel = (
                request.env["slide.channel"].browse(channel_id).exists()
                if channel_id is not False
                else request.env["slide.channel"]
            )
            if not channel:
                return self._redirect_to_slides_main("no_channel")
        if not channel.has_access("read"):
            return self._redirect_to_slides_main("no_rights")

        if category_id and not category:
            category = channel.slide_category_ids.filtered(
                lambda category: category.id == category_id
            )

        domain = self._get_channel_slides_base_domain(channel)
        pager_url = "/slides/%s" % (channel.id)
        pager_args = valid_invite_values.get("pager_args", {})
        slide_categories = dict(
            request.env["slide.slide"]
            ._fields["slide_category"]
            ._description_selection(request.env)
        )

        if search:
            domain &= (
                Domain("name", "ilike", search)
                | Domain("description", "ilike", search)
                | Domain("html_content", "ilike", search)
            )
            pager_args["search"] = search
        else:
            if category:
                domain &= Domain("category_id", "=", category.id)
                pager_url += "/category/%s" % category.id
            elif tag:
                domain &= Domain("tag_ids", "=", tag.id)
                pager_url += "/tag/%s" % tag.id
            if uncategorized:
                domain &= Domain("category_id", "=", False)
                pager_args["uncategorized"] = 1
            elif slide_category:
                domain &= Domain("slide_category", "=", slide_category)
                pager_url += "?slide_category=%s" % slide_category

        # sorting criterion
        if channel.channel_type == "documentation":
            default_sorting = (
                "latest"
                if channel.promote_strategy in ["specific", "none", False]
                else channel.promote_strategy
            )
            actual_sorting = (
                sorting
                if sorting and sorting in request.env["slide.slide"]._order_by_strategy
                else default_sorting
            )
        else:
            actual_sorting = "sequence"
        order = request.env["slide.slide"]._order_by_strategy[actual_sorting]
        pager_args["sorting"] = actual_sorting

        slide_count = request.env["slide.slide"].sudo().search_count(domain)
        page_count = math.ceil(slide_count / self._slides_per_page)
        pager = request.website.pager(
            url=pager_url,
            total=slide_count,
            page=page,
            step=self._slides_per_page,
            url_args=pager_args,
            scope=min(self._pager_max_pages, page_count),
        )

        query_string = None
        if category:
            query_string = "?search_category=%s" % category.id
        elif tag:
            query_string = "?search_tag=%s" % tag.id
        elif slide_category:
            query_string = "?search_slide_category=%s" % slide_category
        elif uncategorized:
            query_string = "?search_uncategorized=1"

        errors = {"access_error": False}
        if request.params.get(
            "access_error"
        ) == "course_content" and request.params.get("access_error_slide_id"):
            # Access are re-verified to support use case where the user refresh the page after an update of their access
            user_slide_authorization = self._get_user_slide_authorization(
                int(request.params.get("access_error_slide_id"))
            )
            if user_slide_authorization["status"] == "not_authorized":
                errors.update(
                    {
                        "access_error": "course_content",
                        "access_error_content_name": request.params.get(
                            "access_error_slide_name"
                        ),
                    }
                )

        render_values = self._slide_render_context_base()
        render_values.update(
            {
                "channel": channel,
                "main_object": channel,
                "active_tab": kw.get("active_tab", "home"),
                # search
                "search_category": category,
                "search_tag": tag,
                "search_slide_category": slide_category,
                "search_uncategorized": uncategorized,
                "query_string": query_string,
                "slide_categories": slide_categories,
                "sorting": actual_sorting,
                "search": search,
                # display data
                "pager": pager,
                "slide_count": slide_count,
                # display upload modal
                "enable_slide_upload": kw.get("enable_slide_upload", False),
                # invitation data
                "invite_hash": invite_hash,
                "invite_partner_id": invite_partner_id,
                "invite_preview": valid_invite_values.get("invite_preview"),
                "is_partner_without_user": valid_invite_values.get(
                    "is_partner_without_user"
                ),
                **errors,
                **self._slide_channel_prepare_review_values(channel),
            }
        )

        # fetch slides and handle uncategorized slides; done as sudo because we want to display all
        # of them but unreachable ones won't be clickable (+ slide controller will crash anyway)
        # documentation mode may display less slides than content by category but overhead of
        # computation is reasonable
        if channel.promote_strategy == "specific":
            render_values["slide_promoted"] = channel.sudo().promoted_slide_id
        else:
            render_values["slide_promoted"] = (
                request.env["slide.slide"].sudo().search(domain, limit=1, order=order)
            )

        limit_category_data = False
        if channel.channel_type == "documentation":
            if category or uncategorized:
                limit_category_data = self._slides_per_page
            else:
                limit_category_data = self._slides_per_category

        render_values["category_data"] = channel._get_categorized_slides(
            domain,
            order,
            force_void=not category,
            limit=limit_category_data,
            offset=pager["offset"],
        )
        render_values["channel_progress"] = self._get_channel_progress(
            channel, include_quiz=True
        )

        # for sys admins: prepare data to install directly modules from eLearning when
        # uploading slides. Currently supporting only survey, because why not.
        if request.env.user.has_group("base.group_system"):
            module = request.env.ref("base.module_survey")
            if module.state != "installed":
                render_values["modules_to_install"] = json.dumps(
                    [
                        {
                            "id": module.id,
                            "name": module.shortdesc,
                            "motivational": _(
                                "Want to test and certify your students?"
                            ),
                            "default_slide_category": "certification",
                        }
                    ]
                )

        render_values = self._prepare_additional_channel_values(render_values, **kw)
        return request.render("website_slides.course_main", render_values)

    @staticmethod
    def _get_channel_values_from_invite(channel_id, invite_hash, invite_partner_id):
        """Check identification parameters and returns values used to give access to signed out invited members.
        The course is returned as sudo to allow them seeing a preview of the course even if visibility if not public.
        Returns dict of values or containing 'invite_error' and a value corresponding to the error. See _get_invite_error_msg."""
        channel_sudo = request.env["slide.channel"].browse(channel_id).exists().sudo()
        partner_sudo = (
            request.env["res.partner"].browse(invite_partner_id).exists().sudo()
        )
        if not partner_sudo or not channel_sudo.is_published:
            return {
                "invite_error": "no_partner"
                if not partner_sudo
                else "no_channel"
                if not channel_sudo
                else "no_rights"
            }

        channel_partner_sudo = channel_sudo.channel_partner_all_ids.filtered(
            lambda cp: cp.partner_id.id == invite_partner_id
        )
        if not channel_partner_sudo:
            return {"invite_error": "expired"}
        if not consteq(channel_partner_sudo._get_invitation_hash(), invite_hash):
            return {"invite_error": "hash_fail"}

        if channel_partner_sudo.member_status == "invited":
            if (
                not channel_partner_sudo.last_invitation_date
                or channel_partner_sudo.last_invitation_date + relativedelta(months=3)
                < fields.Datetime.now()
            ):
                return {"invite_error": "expired"}

        return {
            "invite_channel": channel_sudo,
            "invite_channel_partner": channel_partner_sudo,
            "invite_preview": True,
            "is_partner_without_user": not partner_sudo.user_ids,
            "invite_partner": partner_sudo,
        }

    # SLIDE.CHANNEL UTILS
    # --------------------------------------------------

    @staticmethod
    def _redirect_to_slides_main(invite_error=""):
        return request.redirect(
            f"/slides?invite_error={invite_error}" if invite_error else "/slides"
        )

    @staticmethod
    def _redirect_to_channel(channel):
        return request.redirect(f"/slides/{request.env['ir.http']._slug(channel)}")

    def _slide_channel_prepare_review_values(self, channel):
        values = {
            "rating_avg": channel.sudo().rating_avg,
            "rating_count": channel.sudo().rating_count,
        }

        if not request.env.user._is_public():
            subtype_comment_id = request.env["ir.model.data"]._xmlid_to_res_id(
                "mail.mt_comment"
            )
            last_message = request.env["mail.message"].search(
                [
                    ("model", "=", channel._name),
                    ("res_id", "=", channel.id),
                    ("author_id", "=", request.env.user.partner_id.id),
                    ("message_type", "=", "comment"),
                    ("subtype_id", "=", subtype_comment_id),
                    ("rating_ids", "!=", False),
                ],
                order="write_date DESC",
                limit=1,
            )

            if last_message:
                last_message_values = last_message.read(
                    ["body", "rating_value", "attachment_ids"]
                )[0]
                last_message_attachment_ids = last_message_values.pop(
                    "attachment_ids", []
                )
                if last_message_attachment_ids:
                    # use sudo as portal user cannot read access_token, necessary for updating attachments
                    # through frontend chatter -> access is already granted and limited to current user message
                    last_message_attachment_ids = json.dumps(
                        request.env["ir.attachment"]
                        .sudo()
                        .browse(last_message_attachment_ids)
                        .read(["id", "name", "mimetype", "file_size", "access_token"])
                    )
            else:
                last_message_values = {}
                last_message_attachment_ids = []

            values.update(
                {
                    "last_message_id": last_message_values.get("id"),
                    "last_message": tools.html2plaintext(
                        last_message_values.get("body", "")
                    ),
                    "last_rating_value": last_message_values.get("rating_value"),
                    "last_message_attachment_ids": last_message_attachment_ids,
                }
            )
            if channel.can_review:
                values.update(
                    {
                        "message_post_hash": channel._sign_token(
                            request.env.user.partner_id.id
                        ),
                        "message_post_pid": request.env.user.partner_id.id,
                    }
                )

        return values

    @http.route(
        "/slides/<int:channel_id>/invite",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def slide_channel_invite(self, channel_id, invite_partner_id, invite_hash):
        """This route is included in the invitation link in email to join / check out the course. It is
        the main entry point on the attendee's side when sharing or inviting them. As rule of thumb, this will
        redirect to the course if the rights are given, and to the main /slides page with appropriate error
        message otherwise. (See _get_invite_error_msg method)

        It acts as a redirector:
            - Returns error if parameters are not valid or if expired invitation.
            - If a user is logged, verify the link is for this user. Redirects according to Acl's.
            - If no user is logged:
                - Redirects to login / signup if the partner is enrolled.
                - Redirects to the course with invite parameters. They will be able to browse a course preview
                before logging in / signing up, as prompted in an information banner.

        :param channel_id: The id of the course the user is invited to. Do not use <model> in the route instead,
            otherwise an error 403 could be returned if the (public) user has no access to the record.
        :param invite_partner_id: The id of the invited partner.
        :param invite_hash: The invitation hash that allows a direct access to channel_id, even if not connected.
        """
        channel = request.env["slide.channel"].browse(int(channel_id)).exists()
        if not channel:
            return self._redirect_to_slides_main("no_channel")

        # --- Compute rights of current user
        has_rights = channel.has_access("read")

        invite_values = self._get_channel_values_from_invite(
            channel_id, invite_hash, int(invite_partner_id)
        )
        if invite_values.get("invite_error"):
            return (
                self._redirect_to_channel(channel)
                if has_rights
                else self._redirect_to_slides_main(invite_values.get("invite_error"))
            )

        invite_partner = invite_values.get("invite_partner")
        invite_channel_partner = invite_values.get("invite_channel_partner")

        # --- A user is logged
        if not request.website.is_public_user():
            if request.env.user.partner_id.id != invite_partner.id:
                return self._redirect_to_slides_main("partner_fail")
            return (
                self._redirect_to_channel(channel)
                if has_rights
                else self._redirect_to_slides_main("no_rights")
            )

        redirect_url = f"/slides/{channel_id}"

        # --- No user is logged.
        if invite_channel_partner.member_status != "invited":
            # Enrolled partner. Access to the course but needs to log in / sign up.
            if invite_values.get("is_partner_without_user"):
                invite_partner.signup_prepare()
                signup_url = invite_partner._get_signup_url_for_action(
                    url=redirect_url
                )[invite_partner.id]
                return request.redirect(signup_url)
            else:
                return request.redirect(
                    f"/web/login?redirect={redirect_url}&auth_login={invite_partner.user_ids[0].login}"
                )
        # Pending invitation. A banner will allow partner to login / signup on the course page.
        return request.redirect(
            f"{redirect_url}?invite_partner_id={invite_partner_id}&invite_hash={invite_hash}"
        )

    @http.route(
        ["/slides/<int:channel_id>/identify"],
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def slide_channel_identify_from_invite(
        self, channel_id, invite_partner_id, invite_hash
    ):
        """This route redirects invited partners when they click on the login / signup button, when they are
        asked to login / signup as invited to a course as public user on the course page preview."""
        if not request.website.is_public_user():
            return self._redirect_to_slides_main("identify_fail")

        invite_partner_id = int(invite_partner_id)
        invite_values = self._get_channel_values_from_invite(
            channel_id, invite_hash, invite_partner_id
        )
        if invite_values.get("invite_preview"):
            partner_sudo = invite_values.get("invite_partner")
            if invite_values.get("is_partner_without_user"):
                partner_sudo.signup_prepare()
                return request.redirect(
                    partner_sudo._get_signup_url_for_action(
                        url=f"/slides/{channel_id}"
                    )[partner_sudo.id]
                )
            else:
                return request.redirect(
                    f"/web/login?redirect=/slides/{channel_id}&auth_login={partner_sudo.user_ids[0].login}"
                )
        return self._redirect_to_slides_main("identify_fail")

    @http.route(["/slides/channel/join"], type="jsonrpc", auth="public", website=True)
    def slide_channel_join(self, channel_id):
        # Historical clients sent the id as a string; ``browse`` iterates a
        # multi-character string into bogus ids ("19" -> ('1', '9')).
        channel_id = int(channel_id)
        if request.website.is_public_user():
            return {
                "error": "public_user",
                "error_signup_allowed": request.env["res.users"]
                .sudo()
                ._get_signup_invitation_scope()
                == "b2c",
            }
        channel = request.env["slide.channel"].browse(channel_id)
        if channel.is_member_invited and channel.enroll == "invite":
            success = channel.sudo()._action_add_members(request.env.user.partner_id)
        else:
            success = channel._action_add_members(request.env.user.partner_id)
        return success or {"error": "join_done"}

    @http.route(["/slides/channel/leave"], type="jsonrpc", auth="user", website=True)
    def slide_channel_leave(self, channel_id):
        channel = self._browse_existing("slide.channel", channel_id)
        channel._remove_membership(request.env.user.partner_id.ids)
        self._channel_remove_session_answers(channel)
        return True

    @http.route(
        ["/slides/channel/tag/search_read"],
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        website=True,
    )
    def slide_channel_tag_search_read(self, fields, domain):
        can_create = request.env["slide.channel.tag"].has_access("create")
        return {
            "read_results": request.env["slide.channel.tag"].search_read(
                domain, fields
            ),
            "can_create": can_create,
        }

    @http.route(
        ["/slides/channel/tag/group/search_read"],
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        website=True,
    )
    def slide_channel_tag_group_search_read(self, fields, domain):
        can_create = request.env["slide.channel.tag.group"].has_access("create")
        return {
            "read_results": request.env["slide.channel.tag.group"].search_read(
                domain, fields
            ),
            "can_create": can_create,
        }

    @http.route(
        "/slides/channel/tag/add",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        website=True,
    )
    def slide_channel_tag_add(self, channel_id, tag_id=None, group_id=None):
        """Adds a slide channel tag to the specified slide channel.

        :param integer channel_id: Channel ID
        :param list tag_id: Channel Tag ID as first value of list. If id=0, then this is a new tag to
                            generate and expects a second list value of the name of the new tag.
        :param list group_id: Channel Tag Group ID as first value of list. If id=0, then this is a new
                              tag group to generate and expects a second list value of the name of the
                              new tag group. This value is required for when a new tag is being created.

        tag_id and group_id values are provided by a SelectMenu OWL component. Default "None" values
        allow for graceful failures in exceptional cases when values are not provided.

        :return: channel's course page
        """

        # handle exception during addition of course tag and send error notification to the client
        # otherwise client slide create dialog box continue processing even server fail to create a slide
        try:
            channel = request.env["slide.channel"].browse(int(channel_id)).exists()
            if not channel:
                return {"error": _("This course no longer exists.")}
            can_upload = channel.can_upload
            can_publish = channel.can_publish
        except UserError as e:
            _logger.error(e)
            return {"error": e.args[0]}
        else:
            if not can_upload or not can_publish:
                return {"error": _("You cannot add tags to this course.")}

        # _create_or_get_channel_tag returns *either* a recordset or an error
        # dict; the caller used to .write() on whatever came back, which is an
        # AttributeError when the tag group is missing.
        tag = self._create_or_get_channel_tag(tag_id, group_id)
        if isinstance(tag, dict):
            return tag
        if not tag:
            return {"error": _("No tag to add.")}

        # sudo: slide.channel.tag is officer-only; the right to tag this course
        # was settled by can_upload/can_publish above (see the sudo boundary).
        tag.sudo().write({"channel_ids": [(4, channel.id, 0)]})

        return {"url": "/slides/%s" % (request.env["ir.http"]._slug(channel))}

    @http.route(
        ["/slides/channel/send_share_email"], type="jsonrpc", auth="user", website=True
    )
    def slide_channel_send_share_email(self, channel_id, emails):
        if not email_normalize_all(emails):
            return False
        channel = self._browse_existing("slide.channel", channel_id)
        channel._send_share_email(emails)
        return True

    @http.route(
        ["/slides/channel/subscribe"], type="jsonrpc", auth="user", website=True
    )
    def slide_channel_subscribe(self, channel_id):
        # Presentation Published subtype
        subtype = request.env.ref(
            "website_slides.mt_channel_slide_published", raise_if_not_found=False
        )
        if subtype:
            channel = self._browse_existing("slide.channel", channel_id)
            return channel.message_subscribe(
                partner_ids=[request.env.user.partner_id.id],
                subtype_ids=subtype.ids,
            )
        return True

    @http.route(
        ["/slides/channel/unsubscribe"], type="jsonrpc", auth="user", website=True
    )
    def slide_channel_unsubscribe(self, channel_id):
        self._browse_existing("slide.channel", channel_id).message_unsubscribe(
            partner_ids=[request.env.user.partner_id.id]
        )
        return True

    # --------------------------------------------------
    # SLIDE.SLIDE MAIN / SEARCH
    # --------------------------------------------------

    @http.route(
        '/slides/slide/<model("slide.slide"):slide>',
        type="http",
        auth="public",
        website=True,
        sitemap=True,
        handle_params_access_error=handle_wslide_error,
    )
    def slide_view(self, slide, **kwargs):
        if not slide.channel_id.can_access_from_current_website() or not slide.active:
            raise werkzeug.exceptions.NotFound
        # redirection to channel's homepage for category slides
        if slide.is_category:
            return request.redirect(slide.channel_id.website_absolute_url)

        if (
            slide.can_self_mark_completed
            and not slide.user_has_completed
            and slide.channel_id.channel_type == "training"
            and slide.slide_category != "video"
        ):
            self._slide_mark_completed(slide)
            next_category_to_open = slide._get_next_category()
        else:
            self._set_viewed_slide(slide)
            next_category_to_open = False

        values = self._get_slide_detail(slide)
        # quiz-specific: update with karma and quiz information
        if slide.has_questions:
            values.update(self._get_slide_quiz_data(slide))
        # sidebar: update with user channel progress
        values["channel_progress"] = self._get_channel_progress(
            slide.channel_id, include_quiz=True
        )
        # sidebar: auto-collapsed the categories depending on conditions
        values["category_data"] = self._prepare_collapsed_categories(
            values["category_data"], slide, next_category_to_open
        )

        # Allows to have breadcrumb for the previously used filter
        values.update(
            {
                "search_category": slide.category_id
                if kwargs.get("search_category")
                else None,
                "search_tag": request.env["slide.tag"].browse(
                    int(kwargs.get("search_tag"))
                )
                if kwargs.get("search_tag")
                else None,
                "slide_categories": dict(
                    request.env["slide.slide"]
                    ._fields["slide_category"]
                    ._description_selection(request.env)
                )
                if kwargs.get("search_slide_category")
                else None,
                "search_slide_category": kwargs.get("search_slide_category"),
                "search_uncategorized": kwargs.get("search_uncategorized"),
            }
        )

        values["channel"] = slide.channel_id
        values = self._prepare_additional_channel_values(values, **kwargs)
        values["signup_allowed"] = (
            request.env["res.users"].sudo()._get_signup_invitation_scope() == "b2c"
        )

        if kwargs.get("fullscreen") == "1":
            values.update(self._slide_channel_prepare_review_values(slide.channel_id))
            return request.render("website_slides.slide_fullscreen", values)

        values.pop("channel", None)
        return request.render("website_slides.slide_main", values)

    @http.route(
        "/slides/slide/<int:slide_id>/share",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def slide_shared_view(self, slide_id, **kwargs):
        user_slide_authorization = self._get_user_slide_authorization(slide_id)
        status = user_slide_authorization["status"]
        if status == "not_found":
            raise werkzeug.exceptions.NotFound

        if status == "authorized":
            return request.redirect(
                "%s?%s"
                % (
                    user_slide_authorization["slide"].website_absolute_url,
                    urlencode(kwargs),
                )
            )

        channel_id = user_slide_authorization["channel_id"]
        return request.redirect(
            "/slides/%s?%s"
            % (
                channel_id,
                urlencode(
                    {
                        "access_error": "course_content",
                        "access_error_slide_id": slide_id,
                        "access_error_slide_name": user_slide_authorization[
                            "slide"
                        ].name,
                    }
                ),
            )
        )

    @http.route(
        '/slides/slide/<model("slide.slide"):slide>/pdf_content',
        type="http",
        auth="public",
        website=True,
        sitemap=False,
        handle_params_access_error=handle_wslide_error,
    )
    def slide_get_pdf_content(self, slide):
        response = Response()
        response.data = (
            slide.binary_content and base64.b64decode(slide.binary_content)
        ) or b""
        response.mimetype = "application/pdf"
        return response

    @http.route(
        "/slides/slide/<int:slide_id>/get_image",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def slide_get_image(
        self, slide_id, field="image_128", width=0, height=0, crop=False
    ):
        # Protect infographics by limiting access to 256px (large) images
        if field not in (
            "image_128",
            "image_256",
            "image_512",
            "image_1024",
            "image_1920",
        ):
            return werkzeug.exceptions.Forbidden()

        slide = request.env["slide.slide"].search([("id", "=", int(slide_id))])
        if not slide:
            raise werkzeug.exceptions.NotFound

        return (
            request.env["ir.binary"]
            ._get_stream_image_from_record(
                slide, field, width=int(width), height=int(height), crop=int(crop)
            )
            .get_response()
        )

    # SLIDE.SLIDE UTILS
    # --------------------------------------------------

    @http.route(
        "/slides/slide/get_html_content", type="jsonrpc", auth="public", website=True
    )
    def get_html_content(self, slide_id):
        fetch_res = self._fetch_slide(slide_id)
        if fetch_res.get("error"):
            return fetch_res
        return {
            "html_content": request.env["ir.qweb.field.html"].record_to_html(
                fetch_res["slide"], "html_content", {"template_options": {}}
            )
        }

    @http.route(
        '/slides/slide/<model("slide.slide"):slide>/set_completed',
        website=True,
        type="http",
        auth="user",
        handle_params_access_error=handle_wslide_error,
    )
    def slide_set_completed_and_redirect(self, slide, next_slide_id=None):
        self._slide_mark_completed(slide)
        next_slide = None
        if next_slide_id:
            next_slide = self._fetch_slide(next_slide_id).get("slide", None)
        return request.redirect(
            "/slides/slide/%s"
            % (
                request.env["ir.http"]._slug(next_slide)
                if next_slide
                else request.env["ir.http"]._slug(slide)
            )
        )

    @http.route(
        "/slides/slide/set_completed", website=True, type="jsonrpc", auth="public"
    )
    def slide_set_completed(self, slide_id):
        if request.website.is_public_user():
            return {"error": "public_user"}
        fetch_res = self._fetch_slide(slide_id)
        if fetch_res.get("error"):
            return fetch_res
        self._slide_mark_completed(fetch_res["slide"])
        next_category = fetch_res["slide"]._get_next_category()
        return {
            "channel_completion": fetch_res["slide"].channel_id.completion,
            "next_category_id": next_category.id if next_category else False,
        }

    @http.route(
        '/slides/slide/<model("slide.slide"):slide>/set_uncompleted',
        website=True,
        type="http",
        auth="user",
        handle_params_access_error=handle_wslide_error,
    )
    def slide_set_uncompleted_and_redirect(self, slide):
        self._slide_mark_uncompleted(slide)
        return request.redirect(f"/slides/slide/{request.env['ir.http']._slug(slide)}")

    @http.route(
        "/slides/slide/set_uncompleted", website=True, type="jsonrpc", auth="public"
    )
    def slide_set_uncompleted(self, slide_id):
        if request.website.is_public_user():
            return {"error": "public_user"}
        fetch_res = self._fetch_slide(slide_id)
        if fetch_res.get("error"):
            return fetch_res
        self._slide_mark_uncompleted(fetch_res["slide"])
        return {
            "channel_completion": fetch_res["slide"].channel_id.completion,
            "next_category_id": False,
        }

    @http.route("/slides/slide/like", type="jsonrpc", auth="public", website=True)
    def slide_like(self, slide_id, upvote):
        if request.website.is_public_user():
            return {
                "error": "public_user",
                "error_signup_allowed": request.env["res.users"]
                .sudo()
                ._get_signup_invitation_scope()
                == "b2c",
            }
        # check slide access
        fetch_res = self._fetch_slide(slide_id)
        if fetch_res.get("error"):
            return fetch_res
        # check slide operation
        slide = fetch_res["slide"]
        if not slide.channel_id.is_member:
            return {"error": "channel_membership_required"}
        if not slide.channel_id.allow_comment:
            return {"error": "channel_comment_disabled"}
        if not slide.channel_id.can_vote:
            return {"error": "channel_karma_required"}
        if upvote:
            slide.action_like()
        else:
            slide.action_dislike()
        # for large number of likes/dislikes, format them so they don't break the UI
        # first display is done using a widget but this route updated the UI directly
        # hence calling format_decimalized_number
        return {
            "user_vote": slide.user_vote,
            "likes": tools.misc.format_decimalized_number(slide.likes),
            "dislikes": tools.misc.format_decimalized_number(slide.dislikes),
        }

    @http.route("/slides/slide/archive", type="jsonrpc", auth="user", website=True)
    def slide_archive(self, slide_id):
        """Archive a slide. Publisher action; see the sudo boundary above."""
        slide = self._browse_existing("slide.slide", slide_id)
        self._check_channel_publisher(slide.channel_id)
        slide.sudo().active = False
        return True

    @http.route(
        "/slides/slide/toggle_is_preview", type="jsonrpc", auth="user", website=True
    )
    def slide_preview(self, slide_id):
        """Toggle a slide's preview flag. Publisher action; see the sudo boundary.

        The write used to run under the caller's own rights while the guard
        above it asked for `can_publish`, so the route raised AccessError for
        exactly the users its own guard admitted -- its sibling `slide_archive`
        does the same thing and works only because it happens to sudo.
        """
        slide = self._browse_existing("slide.slide", slide_id)
        self._check_channel_publisher(slide.channel_id)
        slide_sudo = slide.sudo()
        if slide_sudo.slide_category == "certification" and not slide_sudo.is_preview:
            # _check_certification_preview forbids it; say so instead of
            # letting the SQL constraint surface as a 500.
            return {"error": _("A certification cannot be set as a preview.")}
        slide_sudo.is_preview = not slide_sudo.is_preview
        return slide_sudo.is_preview

    @http.route(
        ["/slides/slide/send_share_email"], type="jsonrpc", auth="user", website=True
    )
    def slide_send_share_email(self, slide_id, emails, fullscreen=False):
        if not email_normalize_all(emails):
            return False
        slide = self._browse_existing("slide.slide", slide_id)
        slide._send_share_email(emails, fullscreen)
        return True

    # --------------------------------------------------
    # TAGS SECTION
    # --------------------------------------------------

    @http.route(
        "/slide_channel_tag/add",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        website=True,
    )
    def slide_channel_tag_create_or_get(self, tag_id, group_id):
        tag = self._create_or_get_channel_tag(tag_id, group_id)
        if isinstance(tag, dict):
            return tag
        return {"tag_id": tag.id}

    # --------------------------------------------------
    # QUIZ SECTION
    # --------------------------------------------------

    @http.route(
        "/slides/slide/quiz/question_add_or_update",
        type="jsonrpc",
        methods=["POST"],
        auth="user",
        website=True,
    )
    def slide_quiz_question_add_or_update(
        self, slide_id, question, sequence, answer_ids, existing_question_id=None
    ):
        """Add or update a quiz question on a slide.

        Creates ``survey.question`` + ``survey.question.answer`` records. Auto-
        creates a lightweight survey via ``_check_quiz_survey()`` if needed.
        Resets the creator's completion so they can retake the quiz.

        :param int slide_id: Slide ID
        :param str question: Question title
        :param int sequence: Question sequence
        :param list answer_ids: Answers, each with keys: sequence, text_value,
            is_correct, comment
        :param int existing_question_id: Question ID to replace (delete + create)
        :return: rendered question template
        """
        fetch_res = self._fetch_slide(slide_id)
        if fetch_res.get("error"):
            return fetch_res
        slide = fetch_res["slide"]

        # _fetch_slide only proves read access. Editing a quiz is a publisher
        # action and must be gated like every other mutating route here (see
        # slide_category_add / slide_archive / slide_preview). Without this, the
        # only remaining check was the survey.question ACL, which is not scoped
        # to the courses the caller owns — so anyone holding Survey User rights
        # could rewrite the quiz of a course they have no publish rights on,
        # bypassing rule_slide_slide_officer_cw.
        if not slide.channel_id.can_publish:
            raise werkzeug.exceptions.Forbidden

        # Ensure this slide has a linked survey for questions
        slide._check_quiz_survey()

        new_question_values = {
            "sequence": sequence,
            "title": question,
            "survey_id": slide.survey_id.id,
            "question_type": "simple_choice",
            "suggested_answer_ids": [
                (
                    0,
                    0,
                    {
                        "sequence": answer["sequence"],
                        "value": answer["text_value"],
                        "is_correct": answer["is_correct"],
                        "answer_score": 1.0 if answer["is_correct"] else 0.0,
                        "comment": answer["comment"],
                    },
                )
                for answer in answer_ids
            ],
        }

        try:
            survey_question = request.env["survey.question"].new(new_question_values)
            survey_question._validate_fields(new_question_values.keys())
        except ValidationError as e:
            return {"error": e.args[0]}

        # sudo: same rationale as _check_quiz_survey — the questions of a quiz
        # belong to the slide, and the caller's right to edit them was settled by
        # the can_publish check above. Scoping the search to `slide.survey_id`
        # keeps an id from another course out of reach.
        if existing_question_id:
            request.env["survey.question"].sudo().search(
                [
                    ("survey_id", "=", slide.survey_id.id),
                    ("id", "=", int(existing_question_id)),
                ]
            ).unlink()

        # The editor's own progress is reset so they can re-take the quiz they
        # just changed. Their own row, via the sudo boundary -- searching it
        # under their own rights raised AccessError for a course responsible
        # without an eLearning group. Note this took `slide_id` straight from
        # the request, so a string id silently matched nothing.
        self._get_own_slide_progress_sudo(slide).write({"completed": False})

        survey_question = (
            request.env["survey.question"].sudo().create(new_question_values)
        )
        # Map survey.question fields to the dict keys expected by the QWeb
        # template. Same right as the read side (_get_slide_quiz_data).
        is_editor = slide.channel_id.can_publish
        question_data = {
            "id": survey_question.id,
            "question": survey_question.title,
            "sequence": survey_question.sequence,
            "answer_ids": [
                {
                    "id": a.id,
                    "text_value": a.value,
                    "is_correct": a.is_correct if is_editor else None,
                    "comment": a.comment if is_editor else None,
                }
                for a in survey_question.suggested_answer_ids
            ],
        }
        return request.env["ir.qweb"]._render(
            "website_slides.lesson_content_quiz_question",
            {
                "slide": slide,
                "question": question_data,
            },
        )

    @http.route("/slides/slide/quiz/get", type="jsonrpc", auth="public", website=True)
    def slide_quiz_get(self, slide_id):
        fetch_res = self._fetch_slide(slide_id)
        if fetch_res.get("error"):
            return fetch_res
        slide = fetch_res["slide"]
        return self._get_slide_quiz_data(slide)

    @http.route("/slides/slide/quiz/reset", type="jsonrpc", auth="user", website=True)
    def slide_quiz_reset(self, slide_id):
        """Let the caller re-take a quiz they have already passed.

        Two defects, and they had to be fixed together. The search ran under the
        caller's own rights against the officer-only slide.slide.partner, so the
        route raised AccessError for everyone it is offered to except a Manager
        or the responsible officer -- the "Retake" button simply did nothing.
        And it cleared `completed` and `quiz_attempts_count` without giving the
        karma back, so each pass-then-reset cycle paid the first-attempt reward
        again (measured 10, 20, 30, 40). Repairing only the first would have
        opened the second to everyone.

        `action_mark_uncompleted` is the operation this route always meant:
        it refunds through `_action_set_quiz_done(completed=False)` and leaves
        `quiz_attempts_count` alone, which is what makes the reward ladder
        decay across retries.
        """
        fetch_res = self._fetch_slide(slide_id)
        if fetch_res.get("error"):
            return fetch_res
        slide = fetch_res["slide"]
        if slide.user_has_completed:
            slide.action_mark_uncompleted()
        else:
            self._get_own_slide_progress_sudo(slide).write({"completed": False})
        return None

    @http.route(
        "/slides/slide/quiz/submit", type="jsonrpc", auth="public", website=True
    )
    def slide_quiz_submit(self, slide_id, answer_ids):
        if request.website.is_public_user():
            return {"error": "public_user"}
        fetch_res = self._fetch_slide(slide_id)
        if fetch_res.get("error"):
            return fetch_res
        slide = fetch_res["slide"]

        if slide.user_has_completed:
            self._channel_remove_session_answers(slide.channel_id, slide)
            return {"error": "slide_quiz_done"}

        if not slide.survey_id:
            return {"error": "slide_quiz_incomplete"}

        # sudo: the backing survey is a slide implementation detail (see
        # _get_slide_quiz_data); members without survey groups must still submit.
        all_questions = slide.survey_id.sudo().question_ids.filtered(
            lambda q: not q.is_page
        )
        user_answers = (
            request.env["survey.question.answer"]
            .sudo()
            .search([("id", "in", answer_ids)])
        )
        if user_answers.mapped("question_id") != all_questions:
            return {"error": "slide_quiz_incomplete"}

        user_bad_answers = user_answers.filtered(lambda answer: not answer.is_correct)

        self._set_viewed_slide(slide, quiz_attempts_inc=True)
        quiz_info = self._get_slide_quiz_partner_info(slide, quiz_done=True)

        rank_progress = {}
        if not user_bad_answers:
            rank_progress["previous_rank"] = self._get_rank_values(request.env.user)
            slide._action_mark_completed()
            rank_progress["new_rank"] = self._get_rank_values(request.env.user)
            rank_progress.update(
                {
                    "description": request.env.user.rank_id.description,
                    "last_rank": not request.env.user._get_next_rank(),
                    "level_up": rank_progress["previous_rank"]["lower_bound"]
                    != rank_progress["new_rank"]["lower_bound"],
                }
            )
        self._channel_remove_session_answers(slide.channel_id, slide)
        return {
            "answers": {
                answer.question_id.id: {
                    "is_correct": answer.is_correct,
                    "comment": answer.comment,
                }
                for answer in user_answers
            },
            "completed": slide.user_has_completed,
            "channel_completion": slide.channel_id.completion,
            "quizKarmaWon": quiz_info["quiz_karma_won"],
            "quizKarmaGain": quiz_info["quiz_karma_gain"],
            "quizAttemptsCount": quiz_info["quiz_attempts_count"],
            "rankProgress": rank_progress,
        }

    @http.route(
        ["/slides/slide/quiz/save_to_session"],
        type="jsonrpc",
        auth="public",
        website=True,
    )
    def slide_quiz_save_to_session(self, quiz_answers):
        session_slide_answer_quiz = json.loads(
            request.session.get("slide_answer_quiz", "{}")
        )
        slide_id = quiz_answers["slide_id"]
        session_slide_answer_quiz[str(slide_id)] = quiz_answers["slide_answers"]
        request.session["slide_answer_quiz"] = json.dumps(session_slide_answer_quiz)

    def _get_rank_values(self, user):
        lower_bound = user.rank_id.karma_min or 0
        next_rank = user._get_next_rank()
        upper_bound = next_rank.karma_min
        progress = 100
        if next_rank and (upper_bound - lower_bound) != 0:
            progress = 100 * ((user.karma - lower_bound) / (upper_bound - lower_bound))
        return {
            "lower_bound": lower_bound,
            "upper_bound": upper_bound,
            "karma": user.karma,
            "motivational": next_rank.description_motivational,
            "progress": progress,
        }

    # --------------------------------------------------
    # CATEGORY MANAGEMENT
    # --------------------------------------------------

    @http.route(
        ["/slides/category/search_read"],
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        website=True,
    )
    def slide_category_search_read(self, fields, domain):
        category_slide_domain = Domain(domain or Domain.TRUE) & Domain(
            "is_category", "=", True
        )
        can_create = request.env["slide.slide"].has_access("create")
        return {
            "read_results": request.env["slide.slide"].search_read(
                category_slide_domain, fields
            ),
            "can_create": can_create,
        }

    @http.route(
        "/slides/category/add", type="http", website=True, auth="user", methods=["POST"]
    )
    def slide_category_add(self, channel_id, name):
        """Adds a category to the specified channel. Slide is added at the end
        of slide list based on sequence. Publisher action; see the sudo boundary."""
        channel = self._browse_existing("slide.channel", channel_id)
        channel_sudo = self._check_channel_publisher(channel)

        request.env["slide.slide"].sudo().create(
            self._get_new_slide_category_values(channel_sudo, name)
        )

        return request.redirect("/slides/%s" % (request.env["ir.http"]._slug(channel)))

    # --------------------------------------------------
    # SLIDE.UPLOAD
    # --------------------------------------------------

    @http.route(
        ["/slides/prepare_preview"],
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        website=True,
    )
    def prepare_preview(self, channel_id, slide_category, url=None):
        """Will attempt to fetch external metadata for this slide from the correct
        source (YouTube, Google Drive, ...).

        To take advantage of the slide business method, we create a temporary slide record before
        fetching the metadata.
        This allows a lot of code simplification, since we use "new", it will not created anything
        in database.

        This route drives outbound HTTP to YouTube / Google Drive / Vimeo and
        enumerates a channel's existing videos, and it used to do both for any
        authenticated user with no authorization check at all. It also bound
        `slide` only inside the video / document / infographic branches, so any
        other `slide_category` -- a value that comes straight from the request --
        fell through to an UnboundLocalError.
        """

        if not url:
            return {}

        channel = request.env["slide.channel"].browse(int(channel_id)).exists()
        if not channel:
            return {"error": _("This course no longer exists.")}
        if not channel.can_upload:
            return {"error": _("You cannot upload on this channel.")}
        if slide_category not in ("video", "document", "infographic"):
            return {
                "error": _(
                    "Previews are only available for videos, documents and images."
                )
            }

        Slide = request.env["slide.slide"]

        additional_values = {}
        if slide_category == "video":
            identical_video = request.env["slide.slide"]
            existing_videos = Slide.search(
                [("channel_id", "=", int(channel_id)), ("slide_category", "=", "video")]
            )

            slide = Slide.new(
                {
                    "channel_id": int(channel_id),
                    "name": "memory_record_for_computed_fields",
                    "slide_category": "video",
                    "url": url,
                }
            )

            if not slide.video_source_type:
                return {
                    "error": _(
                        "Could not find your video. Please check if your link is correct and if the video can be accessed."
                    )
                }

            if slide.video_source_type == "youtube":
                identical_video = existing_videos.filtered(
                    lambda existing_video: slide.youtube_id == existing_video.youtube_id
                )
            elif slide.video_source_type == "google_drive":
                identical_video = existing_videos.filtered(
                    lambda existing_video: (
                        slide.google_drive_id == existing_video.google_drive_id
                    )
                )
            elif slide.video_source_type == "vimeo":
                identical_video = existing_videos.filtered(
                    lambda existing_video: slide.vimeo_id == existing_video.vimeo_id
                )
            if identical_video:
                identical_video_name = identical_video[0].name
                additional_values["info"] = _(
                    "This video already exists in this channel on the following content: %s",
                    identical_video_name,
                )
        elif slide_category in ["document", "infographic"]:
            slide = Slide.new(
                {
                    "channel_id": int(channel_id),
                    "name": "memory_record_for_computed_fields",
                    "slide_category": slide_category,
                    "source_type": "external",
                    "url": url,
                }
            )

            if not slide.google_drive_id:
                return {"error": _("Please enter valid Google Drive Link")}

        slide_values, error = slide._get_external_metadata(image_url_only=True)
        if error:
            return {"error": error}

        if additional_values:
            slide_values.update(additional_values)

        return slide_values

    @http.route(
        ["/slides/add_slide"],
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        website=True,
    )
    def create_slide(self, *args, **post):
        # check the size only when we upload a file.
        if post.get("binary_content"):
            file_size = len(post["binary_content"]) * 3 / 4  # base64
            if (file_size / 1024.0 / 1024.0) > 25:
                return {"error": _("File is too big. File size cannot exceed 25MB")}

        values = {
            fname: post[fname]
            for fname in self._get_valid_slide_post_values()
            if post.get(fname)
        }

        # handle exception during creation of slide and sent error notification to the client
        # otherwise client slide create dialog box continue processing even server fail to create a slide
        try:
            channel = request.env["slide.channel"].browse(values["channel_id"])
            can_upload = channel.can_upload
        except UserError as e:
            _logger.error(e)
            return {"error": e.args[0]}
        else:
            if not can_upload:
                return {"error": _("You cannot upload on this channel.")}

        if post.get("duration"):
            # minutes to hours conversion
            values["completion_time"] = int(post["duration"]) / 60

        category = False
        # handle creation of new categories on the fly
        if post.get("category_id"):
            category_id = post["category_id"][0]
            if category_id == 0:
                category = request.env["slide.slide"].create(
                    self._get_new_slide_category_values(
                        channel, post["category_id"][1]["name"]
                    )
                )
                values["sequence"] = category.sequence + 1
            else:
                category = request.env["slide.slide"].browse(category_id)
                values.update(
                    {
                        "sequence": request.env["slide.slide"]
                        .browse(post["category_id"][0])
                        .sequence
                        + 1
                    }
                )

        # create slide itself
        try:
            values["user_id"] = request.env.uid
            slide = request.env["slide.slide"].sudo().create(values)
        except UserError as e:
            _logger.error(e)
            return {"error": e.args[0]}
        except Exception as e:
            _logger.error(e)
            return {
                "error": _(
                    "Internal server error, please try again later or contact administrator.\nHere is the error message: %s",
                    e,
                )
            }

        # ensure correct ordering by re sequencing slides in front-end (backend should be ok thanks to list view)
        channel._resequence_slides(slide, force_category=category)

        redirect_url = "/slides/slide/%s" % (slide.id)
        if slide.slide_category == "article":
            redirect_url = request.env["website"].get_client_action_url(
                redirect_url, True
            )
        elif slide.slide_category == "quiz":
            redirect_url += "?quiz_quick_create"
        elif channel.channel_type == "training":
            redirect_url = "/slides/%s" % (request.env["ir.http"]._slug(channel))
        return {
            "url": redirect_url,
            "channel_type": channel.channel_type,
            "slide_id": slide.id,
            "category_id": slide.category_id,
        }

    def _get_valid_slide_post_values(self):
        return [
            "name",
            "url",
            "video_url",
            "document_google_url",
            "image_google_url",
            "tag_ids",
            "slide_category",
            "channel_id",
            "is_preview",
            "binary_content",
            "description",
            "image_1920",
            "is_published",
            "source_type",
        ]

    @http.route(
        ["/slides/tag/search_read"],
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        website=True,
    )
    def slide_tag_search_read(self, fields, domain):
        can_create = request.env["slide.tag"].has_access("create")
        return {
            "read_results": request.env["slide.tag"].search_read(domain, fields),
            "can_create": can_create,
        }

    # --------------------------------------------------
    # EMBED IN THIRD PARTY WEBSITES
    # --------------------------------------------------

    @http.route(
        "/slides/embed/<int:slide_id>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def slides_embed(self, slide_id, page="1", **kw):
        return self._slide_embed(slide_id, page=page, is_external_embed=False, **kw)

    @http.route(
        "/slides/embed_external/<int:slide_id>",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def slides_embed_external(self, slide_id, page="1", **kw):
        return self._slide_embed(slide_id, page=page, is_external_embed=True, **kw)

    def _slide_embed(self, slide_id, page="1", is_external_embed=False, **kw):
        """Note : don't use the 'model' in the route (use 'slide_id'), otherwise if public cannot
        access the embedded slide, the error will be the website.403 page instead of the one of the
        website_slides.embed_slide.

        Do not forget the rendering here will be displayed in the embedded iframe

        Try accessing slide, and display to corresponding template.

        When the content is embedded *externally*, meaning on a third party website, we do some
        additional steps like displaying sharing controls and also updating some KPIs."""

        try:
            slide = request.env["slide.slide"].browse(slide_id)
            if not slide.exists() or not slide.sudo().active:
                raise werkzeug.exceptions.NotFound

            # Authorization first, and only then anything else. The counter used
            # to be incremented before this check, under sudo, keyed on the
            # Referer header -- so an anonymous client could mint an unbounded
            # number of slide.embed rows carrying arbitrary URLs, against any
            # slide id including unpublished ones, and have them show up in the
            # publisher's backend. Failing here rather than redirecting also
            # keeps the iframe-shaped error page this route exists to serve (see
            # the note above about not using a model converter).
            if not slide.has_access("read"):
                return request.render("website_slides.embed_slide_forbidden", {})

            # redirection to channel's homepage for category slides
            if slide.is_category:
                return request.redirect(slide.channel_id.website_url)

            if is_external_embed:
                referer_url = request.httprequest.headers.get("Referer", "")
                slide.sudo()._embed_increment(referer_url)

            values = self._get_slide_detail(slide)
            values["page"] = page
            values["is_external_embed"] = is_external_embed
            self._set_viewed_slide(slide)
            return request.render("website_slides.embed_slide", values)
        except (
            AccessError
        ):  # TODO : please, make it clean one day, or find another secure way to detect
            # if the slide can be embedded, and properly display the error message.
            return request.render("website_slides.embed_slide_forbidden", {})

    # --------------------------------------------------
    # PROFILE
    # --------------------------------------------------

    def _prepare_user_values(self, **kwargs):
        values = super()._prepare_user_values(**kwargs)
        invite_error_msg = self._get_invite_error_msg(kwargs.get("invite_error"))
        if invite_error_msg:
            values["invite_error_msg"] = invite_error_msg

        channel = self._get_channels(**kwargs)
        if channel:
            values["channel"] = channel
        return values

    def _get_channels(self, **kwargs):
        channels = []
        if kwargs.get("channel"):
            channels = kwargs["channel"]
        elif kwargs.get("channel_id"):
            channels = tools.lazy(
                lambda: request.env["slide.channel"].browse(int(kwargs["channel_id"]))
            )
        return channels

    @staticmethod
    def _get_invite_error_msg(invite_error):
        return {
            "expired": _("This invitation link has expired."),
            "hash_fail": _("This invitation link has an invalid hash."),
            "identify_fail": _("This identification link does not seem to be valid."),
            "no_channel": _("This course does not exist."),
            "no_partner": _(
                "The contact associated with this invitation does not seem to be valid."
            ),
            "no_rights": _("You do not have permission to access this course."),
            "partner_fail": _("This invitation link is not for this contact."),
        }.get(invite_error, "")

    def _prepare_user_slides_profile(self, user):
        courses = (
            request.env["slide.channel.partner"]
            .sudo()
            .search(
                [
                    ("partner_id", "=", user.partner_id.id),
                    ("member_status", "!=", "invited"),
                ]
            )
        )
        courses_completed = courses.filtered(lambda c: c.member_status == "completed")
        courses_ongoing = courses - courses_completed
        return {
            "uid": request.env.user.id,
            "user": user,
            "main_object": user,
            "courses_completed": courses_completed,
            "courses_ongoing": courses_ongoing,
            "is_profile_page": True,
            "badge_category": "slides",
            "my_profile": request.env.user.id == user.id,
        }

    def _prepare_user_profile_values(self, user, **post):
        values = super()._prepare_user_profile_values(user, **post)
        channels = self._get_channels(**post)
        if not channels:
            # Only "is there exactly one?" is asked below, so two is enough to
            # answer it. This used to search every course on the instance on
            # every profile page view.
            channels = request.env["slide.channel"].search([], limit=2)
        values.update(
            self._prepare_user_values(
                channel=channels[0] if len(channels) == 1 else True, **post
            )
        )
        values.update(self._prepare_user_slides_profile(user))
        return values
