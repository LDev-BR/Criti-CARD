"""HTTP surface for community discovery, membership and discussions."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from ..form_security import attempt_budget
from ..progression.types import ProgressionError
from ..security import login_required
from ..uploads import remove_image, save_image
from . import service

bp = Blueprint('communities', __name__, url_prefix='/comunidades')


@bp.before_request
def community_write_budget():
    if request.method == 'POST':
        retry = attempt_budget('community_write')
        if retry:
            raise service.CommunityError(f'Aguarde {retry} segundo(s) antes de tentar novamente.', 429)


@bp.errorhandler(service.CommunityError)
@bp.errorhandler(ProgressionError)
def community_error(error):
    status = getattr(error, 'status', 422)
    return render_template('error.html', code=status, message=str(error)), status


def _community(slug):
    return service._require_community(slug=slug)


def _cleanup_failed_image(filename):
    if filename:
        try:
            remove_image('cover', filename)
        except OSError:
            pass


@bp.get('/')
def index():
    data = service.community_index(g.user['id'] if g.user else None)
    progress = service.access_progress(g.user['id']) if g.user else None
    return render_template('communities/index.html', **data, progress=progress,
        themes=service.THEMES, icons=service.ICONS)


@bp.post('/criar')
@login_required
def create():
    cover = None
    try:
        cover = save_image(request.files.get('cover'), 'cover')
        community = service.create_community(g.user['id'], request.form, cover)
    except (service.CommunityError, ValueError) as error:
        _cleanup_failed_image(cover)
        if isinstance(error, service.CommunityError):
            raise
        raise service.CommunityError(str(error)) from None
    flash('Comunidade criada.', 'success')
    return redirect(url_for('communities.detail', slug=community['slug']))


@bp.get('/<slug>')
def detail(slug):
    page = service.community_page(slug, g.user['id'] if g.user else None)
    if g.user:
        page['progress'] = service.access_progress(g.user['id'])
    page['themes'] = service.THEMES
    page['icons'] = service.ICONS
    return render_template('communities/detail.html', **page)


@bp.post('/<slug>/entrar')
@login_required
def join(slug):
    community = _community(slug)
    service.join_open_community(g.user['id'], community['id'])
    flash('Você entrou na comunidade.', 'success')
    return redirect(url_for('communities.detail', slug=slug))


@bp.post('/<slug>/solicitar')
@login_required
def request_access(slug):
    community = _community(slug)
    service.request_community_access(g.user['id'], community['id'])
    flash('Solicitação enviada para a moderação da comunidade.', 'success')
    return redirect(url_for('communities.detail', slug=slug))


@bp.post('/<slug>/sair')
@login_required
def leave(slug):
    community = _community(slug)
    service.leave_community(g.user['id'], community['id'])
    flash('Você saiu da comunidade.', 'success')
    return redirect(url_for('communities.index'))


@bp.post('/solicitacoes/<int:request_id>/<action>')
@login_required
def resolve_request(request_id, action):
    if action not in ('aprovar','recusar'):
        abort(404)
    service.resolve_join_request(g.user['id'], request_id, action == 'aprovar')
    flash('Solicitação atualizada.', 'success')
    return redirect(request.referrer or url_for('communities.index'))


@bp.post('/solicitacoes/<int:request_id>/cancelar')
@login_required
def cancel_request(request_id):
    service.cancel_join_request(g.user['id'], request_id)
    flash('Solicitação cancelada.', 'success')
    return redirect(request.referrer or url_for('communities.index'))


@bp.post('/convites/<int:invite_id>/<action>')
@login_required
def resolve_invite(invite_id, action):
    if action not in ('aceitar','recusar'):
        abort(404)
    service.resolve_invite(g.user['id'], invite_id, action == 'aceitar')
    flash('Convite atualizado.', 'success')
    return redirect(request.referrer or url_for('communities.index'))


@bp.post('/<slug>/convidar')
@login_required
def invite(slug):
    community = _community(slug)
    service.invite_member(g.user['id'], community['id'], request.form.get('username',''))
    flash('Convite enviado.', 'success')
    return redirect(url_for('communities.detail', slug=slug))


@bp.post('/<slug>/configurar')
@login_required
def configure(slug):
    community = _community(slug)
    cover = None
    try:
        cover = save_image(request.files.get('cover'), 'cover')
        service.update_community(g.user['id'], community['id'], request.form, cover)
    except (service.CommunityError, ValueError) as error:
        _cleanup_failed_image(cover)
        if isinstance(error, service.CommunityError):
            raise
        raise service.CommunityError(str(error)) from None
    flash('Comunidade atualizada.', 'success')
    return redirect(url_for('communities.detail', slug=slug))


@bp.post('/<slug>/membros/<int:member_id>/papel')
@login_required
def member_role(slug, member_id):
    community = _community(slug)
    service.set_member_role(g.user['id'], community['id'], member_id, request.form.get('role'))
    return redirect(url_for('communities.detail', slug=slug))


@bp.post('/<slug>/membros/<int:member_id>/remover')
@login_required
def remove_member(slug, member_id):
    community = _community(slug)
    service.remove_member(g.user['id'], community['id'], member_id)
    flash('Membro removido.', 'success')
    return redirect(url_for('communities.detail', slug=slug))


@bp.post('/<slug>/publicar')
@login_required
def publish(slug):
    community = _community(slug)
    post_id = service.create_post(g.user['id'], community['id'], request.form.get('title',''),
        request.form.get('body',''), request.form.get('work_id'))
    flash('Publicação compartilhada.', 'success')
    return redirect(url_for('communities.post', slug=slug, post_id=post_id))


@bp.get('/<slug>/publicacoes/<int:post_id>')
def post(slug, post_id):
    community = _community(slug)
    data = service.post_detail(post_id, g.user['id'] if g.user else None)
    if data['post']['community_id'] != community['id']:
        abort(404)
    return render_template('communities/post.html', **data, slug=slug)


@bp.post('/<slug>/publicacoes/<int:post_id>/comentar')
@login_required
def comment(slug, post_id):
    community = _community(slug)
    data = service.post_detail(post_id, g.user['id'])
    if data['post']['community_id'] != community['id']:
        abort(404)
    service.create_comment(g.user['id'], post_id, request.form.get('body',''))
    return redirect(url_for('communities.post', slug=slug, post_id=post_id) + '#discussao')


@bp.post('/publicacoes/<int:post_id>/reagir/<kind>')
@login_required
def react(post_id, kind):
    enabled = request.form.get('enabled','true') == 'true'
    service.set_reaction(g.user['id'], post_id, kind, enabled)
    return redirect(request.referrer or url_for('communities.index'))


@bp.post('/publicacoes/<int:post_id>/excluir')
@login_required
def delete_post(post_id):
    community_id = service.delete_post(g.user['id'], post_id)
    community = service._require_community(community_id=community_id, active=False)
    flash('Publicação removida.', 'success')
    return redirect(url_for('communities.detail', slug=community['slug']))


@bp.post('/publicacoes/<int:post_id>/editar')
@login_required
def edit_post(post_id):
    data = service.post_detail(post_id, g.user['id'])
    service.edit_post(g.user['id'], post_id, request.form.get('title',''),
        request.form.get('body',''), request.form.get('work_id'))
    return redirect(url_for('communities.post', slug=data['post']['community_slug'], post_id=post_id))


@bp.post('/comentarios/<int:comment_id>/excluir')
@login_required
def delete_comment(comment_id):
    post_id = service.delete_comment(g.user['id'], comment_id)
    detail = service.post_detail(post_id, g.user['id'])
    return redirect(url_for('communities.post', slug=detail['post']['community_slug'], post_id=post_id))


@bp.post('/comentarios/<int:comment_id>/editar')
@login_required
def edit_comment(comment_id):
    post_id = service.edit_comment(g.user['id'], comment_id, request.form.get('body',''))
    detail = service.post_detail(post_id, g.user['id'])
    return redirect(url_for('communities.post', slug=detail['post']['community_slug'], post_id=post_id))
